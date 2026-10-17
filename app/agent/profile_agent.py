"""The profile agent: which pet-themed titles, in what order, and which venues.

The model chooses the Qloo calls (look up titles, rank them, find venues) and
judges the venues; plain code checks that everything it returns came from
Qloo, then assembles the profile (baseline comparison, lift map) itself.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, NativeOutput, PromptedOutput, RunContext, ToolOutput
from pydantic_ai.models import Model

from app.agent.checks import check_choice_reason
from app.agent.steps import StepLog
from app.locations import Location
from app.profile import VENUE_LIMIT, Entity, rank_band, screen
from app.qloo.envelope import Envelope
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss

TitleKind = Literal["tv_show", "movie", "book", "brand"]
# A lookalike is an animal in a story, so brands are left out.
StoryKind = Literal["tv_show", "movie", "book"]
MAX_RANKED = 5
MAX_VENUE_SIGNALS = 3
MAX_VENUES = 3


@dataclass
class ProfileDeps:
    qloo: QlooClient
    location: Location
    species: str
    log: StepLog
    # The baseline's venue IDs in rank order, or None when unavailable.
    baseline_venues: list[str] | None = None
    # Everything Qloo returned during the run, so the output can be checked against it.
    titles_seen: dict[str, Entity] = field(default_factory=dict)
    ambiguous: dict[str, int] = field(default_factory=dict)
    venues_seen: dict[str, dict[str, Any]] = field(default_factory=dict)
    venue_signals: list[str] | None = None
    # The venues from the latest find_venues call: the only ones the plan may pick,
    # because the profile is assembled from that search.
    latest_venues: set[str] = field(default_factory=set)
    rank_order: list[str] | None = None
    rank_attempted: bool = False


class TitleChoice(BaseModel):
    entity_id: str = Field(description="The Qloo ID from look_up_title.")
    why: str = Field(description="One sentence: why this title is about pets or animals.")
    choice_reason: str | None = Field(
        default=None,
        description="Required when Qloo returned candidates instead of one match: why this one.",
    )


class VenuePick(BaseModel):
    entity_id: str = Field(description="The Qloo ID from find_venues.")
    reason: str = Field(description="One sentence about the place itself.")


class ProfilePlan(BaseModel):
    titles: list[TitleChoice] = Field(description="Best first.", min_length=1, max_length=6)
    venues: list[VenuePick] = Field(
        description="Up to three places to ask about an adoption event or a flyer.",
        max_length=MAX_VENUES,
    )
    rejected_venues: list[VenuePick] = Field(
        default_factory=list, description="Venues you judged unsuitable, with the reason."
    )


INSTRUCTIONS = """\
You help a volunteer at a fictional animal shelter plan where to promote a {species}.
The shelter is in {place}. You use Qloo, a taste-data service, through three tools.

1. Think of 4 to 6 well-known titles (TV shows, films, books or brands) that are clearly
   about {species}s or pets, and that a broad US audience recognises. Avoid titles centred
   on an animal's death, on violence, or coded to a race, religion or political identity.
2. Look each one up with look_up_title. When Qloo offers several candidates, choose the
   pet-themed work you meant and give the reason (year, description). If none fits, drop it.
3. Call rank_titles once, with up to 5 found titles of the same kind, to order them for this
   area. If it is unavailable, keep your own order.
4. Call find_venues with your top 2 or 3 titles. From the venues it returns, and only those,
   choose up to 3 that could host an adoption event or display a flyer: public,
   family-friendly, community places such as cafes, parks, arts centres, bookshops, pet
   shops or breweries with event space. Reject private homes and residences, gyms,
   nightlife-first bars, and anything marked excluded. Qloo lists venues best first, so
   rank 1 is the strongest evidence. Prefer venues with position "top", then "middle", and
   among those prefer venues marked stands_out. Pick a venue with position "bottom" only
   when no higher one is suitable, and then say so in its reason.

Write about places and titles, never about individual people. Keep reasons to one sentence.
"""


def _short(text: str | None, limit: int = 160) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def qloo_call(deps: Any, operation: str, input_: dict[str, Any]) -> Envelope | str:
    """Run a Qloo call; a failure comes back as text the model can read and adapt to."""
    try:
        env = deps.qloo.run(operation, input_)
    except ReplayMiss:
        return "unavailable: this call is not in the cache and live calls are off"
    except QlooExecError as exc:
        return f"unavailable: {exc}"
    if env.status == "error":
        code = env.error.code if env.error else "unknown"
        return f"unavailable: Qloo error {code}"
    return env


def look_up_title(ctx: RunContext[ProfileDeps], name: str, kind: TitleKind) -> dict[str, Any]:
    """Find a title in Qloo by name. Returns the entity, or candidates to choose from."""
    deps = ctx.deps
    deps.log.add("qloo", f"Looking up “{name}” ({kind.replace('_', ' ')}) in Qloo")
    env = qloo_call(deps, "describe", {"entity": name, "type": kind})
    if isinstance(env, str):
        deps.log.add("note", f"“{name}”: {env}")
        return {"status": env}
    if env.status == "needs_input":
        candidates = []
        for c in env.candidates:
            deps.titles_seen[c.id] = Entity(
                id=c.id,
                name=c.name,
                type=c.type,
                description=c.description,
                resolution="chosen",
                alternatives=len(env.candidates) - 1,
            )
            deps.ambiguous[c.id] = len(env.candidates)
            candidates.append(
                {"entity_id": c.id, "name": c.name, "description": _short(c.description)}
            )
        deps.log.add("qloo", f"“{name}” is ambiguous: {len(candidates)} candidates")
        return {"status": "ambiguous", "candidates": candidates}
    if not env.has_results:
        deps.log.add("qloo", f"Qloo has nothing for “{name}”")
        return {"status": "not found"}
    r = env.results[0]
    props = r.get("properties") or {}
    entity = Entity(
        id=r["entity_id"],
        name=r["name"],
        type=r.get("type", f"urn:entity:{kind}"),
        description=props.get("short_description") or props.get("description"),
    )
    deps.titles_seen[entity.id] = entity
    deps.log.add("qloo", f"Found “{entity.name}”")
    return {"status": "found", "entity_id": entity.id, "name": entity.name}


def rank_titles(
    ctx: RunContext[ProfileDeps], entity_ids: list[str], kind: TitleKind
) -> dict[str, Any]:
    """Order up to 5 found titles of one kind by how strong they are in the shelter's area.

    One call per run; Qloo rate-limits this workflow most.
    """
    deps = ctx.deps
    if deps.rank_attempted:
        return {"status": "unavailable: rank_titles can be used once per run"}
    unknown = [i for i in entity_ids if i not in deps.titles_seen]
    if unknown:
        return {"status": f"unknown entity_ids {unknown}; look titles up first"}
    ids = entity_ids[:MAX_RANKED]
    deps.rank_attempted = True
    deps.log.add("qloo", f"Ranking {len(ids)} titles for {deps.location.label}")
    env = qloo_call(
        deps,
        "rank",
        {"option_type": kind, "options": ids, "signal_location": deps.location.query},
    )
    if isinstance(env, str) or not env.has_results or env.status != "ok":
        if isinstance(env, str):
            status = env
        elif not env.has_results:
            status = "unavailable: no ranking returned"
        else:
            # A partial or degraded ranking may have lost the location signal.
            status = f"unavailable: Qloo's ranking was {env.status}"
        deps.log.add("note", f"Ranking {status}; keeping the agent's own order")
        return {"status": status}
    order = [e.entity_id for e in env.entities()]
    deps.rank_order = order
    names = [deps.titles_seen[i].name for i in order if i in deps.titles_seen]
    deps.log.add("qloo", "Order in this area: " + ", ".join(names))
    return {"status": "ranked", "order": order}


def find_venues(ctx: RunContext[ProfileDeps], entity_ids: list[str]) -> dict[str, Any]:
    """Places near the shelter that fans of these titles favour (up to 3 titles)."""
    deps = ctx.deps
    unknown = [i for i in entity_ids if i not in deps.titles_seen]
    if unknown:
        return {"status": f"unknown entity_ids {unknown}; look titles up first"}
    ids = entity_ids[:MAX_VENUE_SIGNALS]
    names = [deps.titles_seen[i].name for i in ids]
    deps.log.add(
        "qloo", f"Finding places near {deps.location.label} for fans of {', '.join(names)}"
    )
    env = qloo_call(
        deps,
        "recommend",
        {
            "target_type": "place",
            "signals": ids,
            "filter_location": deps.location.query,
            "limit": VENUE_LIMIT,
        },
    )
    if isinstance(env, str) or not env.has_results:
        status = env if isinstance(env, str) else "no venues returned"
        deps.log.add("note", f"Venues: {status}")
        return {"status": status}
    deps.venue_signals = ids
    deps.latest_venues = {r["entity_id"] for r in env.results}
    baseline = deps.baseline_venues
    venues = []
    total = len(env.results)
    for rank, r in enumerate(env.results, start=1):
        props = r.get("properties") or {}
        description = props.get("short_description") or props.get("description")
        excluded = screen(description)
        info = {
            "entity_id": r["entity_id"],
            "name": r["name"],
            "neighbourhood": (props.get("geocode") or {}).get("name"),
            "description": _short(description),
            "rank": rank,
            "out_of": total,
            "position": rank_band(rank, total),
            "stands_out": baseline is not None and r["entity_id"] not in baseline,
            "excluded": f"screened out: {excluded}" if excluded else None,
        }
        deps.venues_seen[r["entity_id"]] = info
        venues.append(info)
    stand_out = sum(1 for v in venues if v["stands_out"])
    deps.log.add("qloo", f"{len(venues)} places; {stand_out} stand out against the baseline")
    return {"status": "found", "venues": venues}


def check_plan(ctx: RunContext[ProfileDeps], plan: ProfilePlan) -> ProfilePlan:
    """Everything in the plan must come from Qloo during this run."""
    deps = ctx.deps
    problems = []
    for t in plan.titles:
        if t.entity_id not in deps.titles_seen:
            problems.append(f"title {t.entity_id} was not returned by look_up_title")
        elif deps.ambiguous.get(t.entity_id) and not t.choice_reason:
            problems.append(f"title {t.entity_id} had several candidates; give choice_reason")
        if t.choice_reason:
            problems += check_choice_reason(t.choice_reason, f"the choice_reason for {t.entity_id}")
    for v in plan.venues:
        info = deps.venues_seen.get(v.entity_id)
        if info is None:
            problems.append(f"venue {v.entity_id} was not returned by find_venues")
        elif v.entity_id not in deps.latest_venues:
            problems.append(
                f"venue {info['name']} is from an earlier search; pick from your latest "
                "find_venues results"
            )
        elif info["excluded"]:
            problems.append(f"venue {info['name']} is {info['excluded']}")
    if deps.titles_seen and deps.venue_signals is None and not plan.venues:
        problems.append("call find_venues before answering")
    if problems:
        deps.log.add("check", "Sent back for a fix: " + "; ".join(problems))
        raise ModelRetry("Fix these and answer again: " + "; ".join(problems))
    deps.log.add("check", "Plan checked: every title and venue came from Qloo")
    return plan


def output_spec(mode: str):
    if mode == "prompted":
        return PromptedOutput(ProfilePlan)
    if mode == "tool":
        return ToolOutput(ProfilePlan)
    return NativeOutput(ProfilePlan)


def build_profile_agent(
    model: Model, output_mode: str = "native"
) -> Agent[ProfileDeps, ProfilePlan]:
    agent = Agent(
        model,
        deps_type=ProfileDeps,
        output_type=output_spec(output_mode),
        # One repair round after a failed check, as the brief asks.
        retries=1,
        tools=[look_up_title, rank_titles, find_venues],
    )

    @agent.instructions
    def instructions(ctx: RunContext[ProfileDeps]) -> str:
        loc = ctx.deps.location
        return INSTRUCTIONS.format(species=ctx.deps.species, place=f"{loc.label}, {loc.region}")

    agent.output_validator(check_plan)
    return agent
