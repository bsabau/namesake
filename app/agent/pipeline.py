"""One run for one animal at one location: profile (reused when saved), then listing.

Every failure has a fallback that is said out loud in the step log and on the page:
- the profile agent fails: the fixed seed lookup from milestone 2;
- the listing agent fails its checks twice, or the model is unavailable: the
  templated listing, which uses only recorded facts.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable

from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.exceptions import AgentRunError, ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from app.agent.listing_agent import BioSentence, ListingDeps, build_listing_agent, hook_for
from app.agent.profile_agent import ProfileDeps, build_profile_agent
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.animals import Animal
from app.listing import check_sentences, pronouns
from app.locations import Location
from app.profile import (
    Entity,
    LocationProfile,
    Seeds,
    baseline_venue_ids,
    build_profile,
    local_tastes,
    profile_from,
    resolve_baseline,
)
from app.qloo.exec import QlooClient
from app.store import Store

# Bounds on one agent run: model requests and tool calls.
PROFILE_LIMITS = UsageLimits(request_limit=16, tool_calls_limit=14)
LISTING_LIMITS = UsageLimits(request_limit=4)

ModelFactory = Callable[[], Model]

# One profile build per location and species at a time; a second request waits and
# then finds the saved profile instead of spending quota on the same work.
_profile_locks: defaultdict[tuple[int, str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
# One listing at a time per shelter, so the names already taken are read and the new
# listing saved without another run giving out the same name in between.
_listing_locks: defaultdict[tuple[int, str], asyncio.Lock] = defaultdict(asyncio.Lock)
AGENT_FAILURES = (UnexpectedModelBehavior, AgentRunError, ModelHTTPError, OSError, ValueError)


async def agent_profile(
    qloo: QlooClient,
    location: Location,
    species: str,
    seeds: Seeds,
    model: Model,
    log: StepLog,
    output_mode: str,
) -> LocationProfile:
    log.add("start", f"Building the profile for {species}s in {location.label}")
    baseline = await asyncio.to_thread(resolve_baseline, qloo, location, seeds.baseline)
    base_ids = None
    if baseline is not None:
        log.add("qloo", f"Baseline: places near {location.label} for fans of {baseline.name}")
        base_ids = await asyncio.to_thread(baseline_venue_ids, qloo, location, baseline)

    deps = ProfileDeps(
        qloo=qloo, location=location, species=species, log=log, baseline_venues=base_ids
    )
    agent = build_profile_agent(model, output_mode)
    run = await agent.run("Build the profile.", deps=deps, usage_limits=PROFILE_LIMITS)
    plan = run.output

    chosen = {t.entity_id: t for t in plan.titles}
    order = [i for i in (deps.rank_order or []) if i in chosen]
    order += [t.entity_id for t in plan.titles if t.entity_id not in order]
    pets = []
    for entity_id in order:
        entity = deps.titles_seen[entity_id].model_copy()
        entity.why = chosen[entity_id].why
        entity.choice_reason = chosen[entity_id].choice_reason
        pets.append(entity)

    profile = await asyncio.to_thread(
        profile_from, qloo, location, pets, baseline, deps.venue_signals
    )
    picks = {v.entity_id: v.reason for v in plan.venues}
    rejects = {v.entity_id: v.reason for v in plan.rejected_venues}
    for venue in profile.venues:
        venue.chosen_reason = picks.get(venue.entity_id)
        venue.rejected_reason = rejects.get(venue.entity_id)
    profile.made_by = "agent"
    profile.order_source = "qloo_rank" if deps.rank_order else "agent"
    # Qloo's full order, so a badge reports the position Qloo actually gave.
    profile.ranked = list(deps.rank_order or [])
    return profile


async def get_profile(
    animal: Animal,
    location: Location,
    *,
    qloo: QlooClient,
    store: Store,
    seeds: Seeds,
    model_factory: ModelFactory | None,
    log: StepLog,
    output_mode: str,
) -> LocationProfile:
    species = animal.species
    loop = id(asyncio.get_running_loop())
    async with _profile_locks[(loop, location.id, species)]:
        saved = store.get_profile(location.id, species)
        if saved is not None:
            log.add("note", f"Using the saved profile for {species}s in {location.label}")
            return saved
        return await _build_profile(
            animal,
            location,
            qloo=qloo,
            store=store,
            seeds=seeds,
            model_factory=model_factory,
            log=log,
            output_mode=output_mode,
        )


async def _build_profile(
    animal: Animal,
    location: Location,
    *,
    qloo: QlooClient,
    store: Store,
    seeds: Seeds,
    model_factory: ModelFactory | None,
    log: StepLog,
    output_mode: str,
) -> LocationProfile:
    species = animal.species

    profile = None
    if model_factory is not None:
        try:
            profile = await agent_profile(
                qloo, location, species, seeds, model_factory(), log, output_mode
            )
        except AGENT_FAILURES as exc:
            log.add("error", f"The profile agent did not finish ({type(exc).__name__})")
    if profile is None:
        log.add("note", "Falling back to the fixed lookup with the seed titles")
        profile = await asyncio.to_thread(build_profile, qloo, location, seeds)

    profile.species = species
    log.add("qloo", f"Looking up what people around {location.label} tend to watch")
    profile.local_tastes = await asyncio.to_thread(local_tastes, qloo, location)
    store.put_profile(profile)
    return profile


def taken_names(
    animal: Animal, location: Location, store: Store, roster_litter: set[str]
) -> frozenset[str]:
    """First names already given to other animals at this shelter, except litter mates."""
    names = set()
    for other in store.listings_at(location.id):
        if other.animal_id == animal.id or other.animal_id in roster_litter:
            continue
        if other.draft is not None:
            names.add(other.draft.names[0].name.lower())
    return frozenset(names)


async def write_listing(
    animal: Animal,
    location: Location,
    profile: LocationProfile,
    *,
    model_factory: ModelFactory | None,
    log: StepLog,
    output_mode: str,
    taken: frozenset[str] = frozenset(),
) -> ListingResult:
    result = ListingResult(
        animal_id=animal.id, location_id=location.id, checks_version=CHECKS_VERSION
    )
    if model_factory is None:
        result.fallback_reason = "No model is configured, so this is the templated listing."
        return result
    titles: dict[str, tuple[Entity, str]] = {e.id: (e, "pet") for e in profile.pet_entities}
    for e in profile.local_tastes:
        titles.setdefault(e.id, (e, "local"))
    if not titles:
        result.fallback_reason = "Qloo returned no titles to draw names from."
        return result

    log.add("start", f"Writing the listing and name options for the {animal.species}")
    agent = build_listing_agent(model_factory(), output_mode)
    try:
        run = await agent.run(
            "Write the listing.",
            deps=ListingDeps(animal=animal, titles=titles, log=log, taken_names=taken),
            usage_limits=LISTING_LIMITS,
        )
        result.draft = run.output
        # The confirmed checks come from fixed sentences, never from the model.
        result.bio = list(run.output.bio) + [
            BioSentence(text=c.text, facts=[c.source])
            for c in check_sentences(animal.checks, pronouns(animal.sex))
        ]
        result.hook = hook_for(run.output.names[0])
    except AGENT_FAILURES as exc:
        log.add("error", f"The listing did not pass its checks ({type(exc).__name__})")
        result.fallback_reason = (
            "The agent's draft did not pass the checks after one repair, so this is the "
            "templated listing."
        )
    return result


async def run_pipeline(
    animal: Animal,
    location: Location,
    *,
    qloo: QlooClient,
    store: Store,
    seeds: Seeds,
    model_factory: ModelFactory | None,
    log: StepLog,
    output_mode: str = "native",
    litter_mates: set[str] | None = None,
) -> ListingResult:
    """Profile, then listing. The caller finishes the log, after reporting any error."""
    profile = await get_profile(
        animal,
        location,
        qloo=qloo,
        store=store,
        seeds=seeds,
        model_factory=model_factory,
        log=log,
        output_mode=output_mode,
    )
    async with _listing_locks[(id(asyncio.get_running_loop()), location.id)]:
        result = await write_listing(
            animal,
            location,
            profile,
            model_factory=model_factory,
            log=log,
            output_mode=output_mode,
            taken=taken_names(animal, location, store, litter_mates or set()),
        )
        result.steps = list(log.steps)
        store.put_listing(result)
    log.add("done", "Done")
    return result
