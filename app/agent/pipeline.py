"""One run for one animal at one location: profile (reused when saved), then listing.

Every failure has a fallback that is said out loud in the step log and on the page:
- the profile agent fails: the fixed seed lookup from milestone 2;
- the listing agent fails its checks twice, or the model is unavailable: the
  templated listing, which uses only recorded facts.
"""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence

import anthropic
import openai
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from app.agent.checks import hook_text, reference_key
from app.agent.listing_agent import (
    ListingDeps,
    build_listing_agent,
    reference_for,
    shown_bio,
)
from app.agent.model import ModelChoice
from app.agent.profile_agent import ProfileDeps, build_profile_agent, has_evidence, pet_lists
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.animals import ADDED_PREFIX, Animal
from app.audience import add_audiences
from app.classify import JevClassifier
from app.locations import Location
from app.profile import (
    PROFILE_VERSION,
    Entity,
    LocationProfile,
    Prepared,
    Seeds,
    baseline_for,
    baseline_venue_ids,
    build_profile,
    finish_profile,
    needs_finishing,
    profile_from,
)
from app.qloo.exec import QlooClient
from app.store import Store
from app.venue_points import save_keeping_points

# Bounds on one agent run: model requests and tool calls.
# The profile's budget allows up to three find_local_titles searches (decision 20).
# 20 tool calls: the caps on lookups (10), searches (3), venue searches (3) and the ranking
# (1) leave room for a repair round's call.
PROFILE_LIMITS = UsageLimits(request_limit=21, tool_calls_limit=20)
LISTING_LIMITS = UsageLimits(request_limit=6, tool_calls_limit=4)

ModelFactory = Callable[[], Model]
# Each run's model usage (requests and tokens) goes to the server log, to watch the cost.
logger = logging.getLogger(__name__)

# One profile build per location and species at a time; a second request waits and
# then finds the saved profile instead of spending quota on the same work.
_profile_locks: defaultdict[tuple[int, str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
# One listing at a time per shelter, so the names already taken are read and the new
# listing saved without another run giving out the same name in between.
_listing_locks: defaultdict[tuple[int, str], asyncio.Lock] = defaultdict(asyncio.Lock)
# The SDKs' own base errors too: an error inside a stream, after the HTTP 200, can surface
# as one that PydanticAI does not wrap (Anthropic's, as of 2.56).
SDK_ERRORS = (anthropic.APIError, openai.APIError)
AGENT_FAILURES = (
    UnexpectedModelBehavior, AgentRunError, ModelHTTPError, OSError, ValueError, *SDK_ERRORS
)  # fmt: skip
# What starts a run again on the next model: the model could not be reached, refused the
# request, or ran out of time (TimeoutError is an OSError). A draft that fails its checks
# is not one: it falls to the template as before.
MODEL_FAILURES = (ModelAPIError, OSError, *SDK_ERRORS)
# Seconds one model may spend on a whole run, its tool calls included, before the next
# model is tried: room for a request that times out and succeeds on its retry
# (app/agent/model.py), and for the slowest model measured (decision 25). A synchronous
# tool already running when the cap lands (a `qloo` call with its retries: minutes, for a
# refused `rank`) is not interrupted: its thread finishes in the background.
PROFILE_TIMEOUT = 480.0
LISTING_TIMEOUT = 300.0
Fallbacks = Sequence[ModelChoice]


def models_in_order(
    model_factory: ModelFactory | None, output_mode: str, fallbacks: Fallbacks
) -> list[ModelChoice]:
    """The main model, then the fallbacks."""
    main = [ModelChoice(model_factory, output_mode)] if model_factory is not None else []
    return main + list(fallbacks)


async def on_each_model[T](
    models: list[ModelChoice], attempt: Callable[[ModelChoice], Awaitable[T]], log: StepLog
) -> T:
    """`attempt` on each model in turn until one is reached; the last one's failure is
    raised. Saved Qloo answers are reused, so starting again costs no Qloo quota beyond
    any call the earlier attempt had not finished."""
    for i, choice in enumerate(models):
        try:
            return await attempt(choice)
        except MODEL_FAILURES as exc:
            if i == len(models) - 1:
                raise
            log.add("note", "Namesake's AI could not be reached; starting again on a backup model")
            logger.warning("model %d of %d failed: %s", i + 1, len(models), type(exc).__name__)
    raise ValueError("no model to run")


async def agent_profile(
    qloo: QlooClient,
    location: Location,
    species: str,
    seeds: Seeds,
    model: Model,
    log: StepLog,
    output_mode: str,
    prepared: Prepared,
    classifier: JevClassifier | None = None,
) -> LocationProfile:
    # The baseline was fixed before the AI runs (`_build_profile`), so its venue choices
    # are judged against the same comparison the page shows.
    tastes, baselines, source, notes = prepared
    base_ids, filtered = None, None
    if baselines:
        log.add("qloo", f"Baseline: places near {location.label} for fans of its top shows")
        filtered, base_ids = await asyncio.to_thread(baseline_venue_ids, qloo, location, baselines)

    deps = ProfileDeps(
        qloo=qloo,
        location=location,
        species=species,
        log=log,
        baseline_venues=base_ids,
        venue_filter=filtered,
        baseline_titles={e.id: e.name for e in baselines},
        classifier=classifier,
    )
    agent = build_profile_agent(model, output_mode)
    # Qloo's own pet-themed lists for the area come first; the AI starts from them.
    found = await asyncio.to_thread(pet_lists, deps)
    prompt = (
        "Build the profile. Qloo's lists for this area, asked with its pet tags: "
        + json.dumps(found, ensure_ascii=False)
    )
    if baselines:
        # Said up front, so no lookup or repair round is spent on them.
        names = " and ".join(e.name for e in baselines)
        what = "this area's top shows" if source == "area" else "the show used"
        them = "them" if len(baselines) > 1 else "it"
        prompt += f" {names}: {what} for the comparison; do not propose {them} as pet titles."
    run = await agent.run(prompt, deps=deps, usage_limits=PROFILE_LIMITS)
    logger.info("profile run for %s, %s: %s", location.id, species, run.usage)
    plan = run.output

    chosen = {t.entity_id: t for t in plan.titles}
    # A title stays only with Qloo's evidence for the area, when any title has it. The
    # venues were asked for backed titles when the AI sent any (find_venues); a title they
    # were asked for stays whatever its evidence, since the venues and the map rest on it.
    backed = [i for i in chosen if has_evidence(deps, i)]
    asked = deps.venue_signals or []
    keep = [i for i in chosen if i in backed or i in asked]
    left_out = [deps.titles_seen[i].name for i in chosen if backed and i not in keep]
    if left_out:
        log.add(
            "check",
            f"Left out {', '.join(left_out)}: Qloo neither ranks them here nor lists them for "
            "this area",
        )
        chosen = {i: chosen[i] for i in keep}
    order = [i for i in (deps.rank_order or []) if i in chosen]
    order += [
        t.entity_id for t in plan.titles if t.entity_id in chosen and t.entity_id not in order
    ]
    pets = []
    for entity_id in order:
        entity = deps.titles_seen[entity_id].model_copy()
        entity.why = chosen[entity_id].why
        entity.choice_reason = chosen[entity_id].choice_reason
        pets.append(entity)

    profile = await asyncio.to_thread(
        profile_from, qloo, location, pets, baselines, deps.venue_signals, deps.venue_filter
    )
    profile.local_tastes, profile.baseline_source = tastes, source
    profile.notes = notes + profile.notes
    # The calls behind the titles first (Qloo's pet-tag lists, then the AI's own lookups,
    # searches and ranking), then the assembly's.
    profile.calls = deps.calls + profile.calls
    picks = {v.entity_id: v.reason for v in plan.venues}
    rejects = {v.entity_id: v.reason for v in plan.rejected_venues}
    for venue in profile.venues:
        venue.chosen_reason = picks.get(venue.entity_id)
        venue.rejected_reason = rejects.get(venue.entity_id)
    profile.made_by = "agent"
    profile.left_out_titles, profile.titles_confirmed = left_out, bool(backed)
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
    classifier: JevClassifier | None = None,
    fallbacks: Fallbacks = (),
) -> LocationProfile:
    species = animal.species
    loop = id(asyncio.get_running_loop())
    async with _profile_locks[(loop, location.id, species)]:
        saved = store.get_profile(location.id, species)
        if saved is not None and saved.version >= PROFILE_VERSION and needs_finishing(saved):
            # Saved unfinished, or with a comparison today's screen would not choose: finish
            # it around the same titles, so listings made from it keep their evidence. Fixed
            # calls only; what is cached costs nothing.
            log.add("note", f"Finishing the saved profile for {species}s in {location.label}")
            finished = await asyncio.to_thread(finish_profile, saved, location, qloo, seeds)
            if finished is not None:
                # Venues pinned while this ran (app/venue_points.py) keep their points.
                finished.species = species
                await asyncio.to_thread(save_keeping_points, store, finished, location.id)
                return finished
            log.add("note", "Qloo could not finish it yet; using it as it is")
            return saved
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
            classifier=classifier,
            fallbacks=fallbacks,
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
    classifier: JevClassifier | None = None,
    fallbacks: Fallbacks = (),
) -> LocationProfile:
    species = animal.species
    log.add("start", f"Building the profile for {species}s in {location.label}")
    # The baseline is what the area watches most, leaving out shows that mention animals
    # (decision 18): looked up once here, for the AI's run and the fallback alike. The step
    # log names no title: the Why panel does.
    log.add("qloo", f"Looking up what people around {location.label} tend to watch")
    prepared = await asyncio.to_thread(baseline_for, qloo, location, seeds)

    profile = None
    models = models_in_order(model_factory, output_mode, fallbacks)
    if models:

        def attempt(choice: ModelChoice) -> Awaitable[LocationProfile]:
            run = agent_profile(
                qloo,
                location,
                species,
                seeds,
                choice.make(),
                log,
                choice.output_mode,
                prepared,
                classifier,
            )
            return asyncio.wait_for(run, PROFILE_TIMEOUT)

        try:
            profile = await on_each_model(models, attempt, log)
        except AGENT_FAILURES as exc:
            log.add(
                "error", f"Namesake's AI did not finish the area profile ({type(exc).__name__})"
            )
    if profile is None:
        log.add("note", "Falling back to the fixed lookup with the seed titles")
        profile = await asyncio.to_thread(build_profile, qloo, location, seeds, prepared, species)

    profile.species = species
    # Saved even when unfinished, so a listing made now keeps its titles' evidence; the
    # next run finishes it (get_profile). A profile with no titles has nothing to finish.
    if not profile.pet_entities:
        log.add("note", "No pet-themed title could be found; the next run tries again")
        return profile
    store.put_profile(profile)
    if not profile.complete:
        log.add("note", "Qloo could not finish this area's profile; the next run finishes it")
    return profile


def taken_names(
    animal: Animal, location: Location, store: Store, also: frozenset[str] = frozenset()
) -> frozenset[str]:
    """Names other animals at this shelter have: each saved listing's first name, and
    every name approved for another shared animal. Litter mates included: a litter shares
    a title, never a name. Names approved for animals a visitor added stay private to
    that visit (decision 9); the caller passes the visit's own names as `also`."""
    names = set(also)
    # Listings saved before the checks last changed too: their names stay in use until
    # they are written again (19 October audit).
    for other in store.listings_at(location.id, current_only=False):
        if other.animal_id != animal.id and other.draft is not None:
            names.add(other.draft.names[0].name.lower())
    for animal_id, approved in store.approved_names(location.id).items():
        if animal_id != animal.id and not animal_id.startswith(ADDED_PREFIX):
            names |= approved
    return frozenset(names)


def taken_references(
    animal: Animal, location: Location, store: Store
) -> dict[tuple[str, tuple[str, ...]], str]:
    """What other animals at this shelter are named after: the reference of each saved
    listing's first name and of every name approved for that animal, keyed by title and
    character (checks.reference_key, compared with checks.same_reference), with a label
    for the instructions. Two animals never
    share a reference; a litter's mates share a title, never a character."""
    approved = store.approved_names(location.id)
    refs: dict[tuple[str, tuple[str, ...]], str] = {}
    for other in store.listings_at(location.id, current_only=False):
        if other.animal_id == animal.id or other.draft is None:
            continue
        used = {other.draft.names[0].name.lower()} | approved.get(other.animal_id, set())
        for i, option in enumerate(other.draft.names):
            if option.name.lower() in used:
                label = other.references[i] if i < len(other.references) else option.character
                refs[reference_key(option.entity_id, option.character)] = label
    return refs


def litter_theme(location: Location, store: Store, mates: set[str]) -> str | None:
    """The title a litter's saved members were named from, if any have been."""
    for mate in sorted(mates):
        # Saved before the checks last changed too, as for the names taken: a mate whose
        # listing awaits a rerun still holds the litter's title.
        saved = store.get_listing(mate, location.id, current_only=False)
        if saved is not None and saved.draft is not None:
            return saved.draft.names[0].entity_id
    return None


def name_titles(
    profile: LocationProfile, theme: str | None = None, first_of_litter: bool = False
) -> dict[str, tuple[Entity, str]]:
    """The titles a listing may take names from: the area's pet-themed titles, then its
    local tastes. A litter named as a set keeps to its theme; its first member, which
    picks the theme, picks among the pet-themed titles when the area has any, so a litter
    is never named after a show from the area's general watch list (22 October: the Park
    Slope kittens were named from an adult comedy)."""
    titles: dict[str, tuple[Entity, str]] = {e.id: (e, "pet") for e in profile.pet_entities}
    for e in profile.local_tastes:
        titles.setdefault(e.id, (e, "local"))
    if theme is not None:
        return {k: v for k, v in titles.items() if k == theme}
    if first_of_litter:
        return {k: v for k, v in titles.items() if v[1] == "pet"} or titles
    return titles


async def write_listing(
    animal: Animal,
    location: Location,
    profile: LocationProfile,
    *,
    model_factory: ModelFactory | None,
    log: StepLog,
    output_mode: str,
    taken: frozenset[str] = frozenset(),
    taken_refs: dict[tuple[str, tuple[str, ...]], str] | None = None,
    request: str | None = None,
    theme: str | None = None,
    first_of_litter: bool = False,
    qloo: QlooClient | None = None,
    fallbacks: Fallbacks = (),
) -> ListingResult:
    """One listing. `request` is a volunteer's refine request. For a litter named as a
    set, `theme` limits the names to the litter's title, and the first member's names
    must all come from one title, which becomes the theme. With `qloo`, the agent may
    look up titles featuring an animal that looks like this one."""
    result = ListingResult(
        animal_id=animal.id, location_id=location.id, checks_version=CHECKS_VERSION
    )
    models = models_in_order(model_factory, output_mode, fallbacks)
    if not models:
        result.fallback_reason = "No model is configured, so this is the templated listing."
        return result
    titles = name_titles(profile, theme, first_of_litter)
    if not titles:
        result.fallback_reason = "Qloo returned no titles to draw names from."
        return result

    log.add("start", f"Writing the listing and name options for the {animal.species}")

    async def attempt(choice: ModelChoice):
        agent = build_listing_agent(choice.make(), choice.output_mode)
        deps = ListingDeps(
            animal=animal,
            titles=dict(titles),
            log=log,
            taken_names=taken,
            taken_references=taken_refs or {},
            request=request,
            litter_title=titles[theme][0].name if theme else None,
            first_of_litter=first_of_litter,
            qloo=qloo,
        )
        # The lookup tool is synchronous and runs `qloo` as a subprocess; PydanticAI
        # runs sync tools in a worker thread.
        run = agent.run("Write the listing.", deps=deps, usage_limits=LISTING_LIMITS)
        return await asyncio.wait_for(run, LISTING_TIMEOUT), deps

    try:
        run, deps = await on_each_model(models, attempt, log)
        logger.info("listing run for %s at %s: %s", animal.id, location.id, run.usage)
        result.draft = run.output
        result.bio = shown_bio(animal, run.output)
        # deps.titles now includes any lookalike titles the agent found.
        result.references = [
            reference_for(o, deps.titles[o.entity_id][0].name) for o in run.output.names
        ]
        result.hook = hook_text(result.references[0])
        used = {o.entity_id for o in run.output.names}
        result.lookalikes = [v for k, v in deps.lookalikes.items() if k in used]
    except MODEL_FAILURES as exc:
        # No model answered: there was no draft to check (Flash review, PR #42).
        # The visitor reads the step; the exception's name is for the server's log only.
        logger.warning("listing: no model answered (%s)", type(exc).__name__)
        log.add("error", "Namesake's AI could not be reached")
        result.fallback_reason = (
            "Namesake's AI could not be reached, so this is the templated listing."
        )
    except AGENT_FAILURES as exc:
        logger.warning("listing: the draft failed its checks (%s)", type(exc).__name__)
        log.add("error", "The listing did not pass its checks after one repair")
        result.fallback_reason = (
            "The draft from Namesake's AI did not pass the checks after one repair, so this is "
            "the templated listing."
        )
    return result


Save = Callable[[ListingResult], None]


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
    request: str | None = None,
    save: Save | None = None,
    also_taken: frozenset[str] = frozenset(),
    classifier: JevClassifier | None = None,
    fallbacks: Fallbacks = (),
) -> ListingResult:
    """Profile, then listing. The caller finishes the log, after reporting any error.

    `save` keeps the listing somewhere other than the shared store: a refined listing
    or an added animal's listing belongs to one visitor's session.
    """
    profile = await get_profile(
        animal,
        location,
        qloo=qloo,
        store=store,
        seeds=seeds,
        model_factory=model_factory,
        log=log,
        output_mode=output_mode,
        classifier=classifier,
        fallbacks=fallbacks,
    )
    async with _listing_locks[(id(asyncio.get_running_loop()), location.id)]:
        theme = litter_theme(location, store, litter_mates or set())
        result = await write_listing(
            animal,
            location,
            profile,
            model_factory=model_factory,
            log=log,
            output_mode=output_mode,
            taken=taken_names(animal, location, store, also_taken),
            taken_refs=taken_references(animal, location, store),
            request=request,
            # A litter member written on its own keeps to the title its mates share,
            # or, as the first one named, takes all its names from one title.
            theme=theme,
            first_of_litter=bool(litter_mates) and theme is None,
            qloo=qloo,
            fallbacks=fallbacks,
        )
        await asyncio.to_thread(add_audiences, result, qloo, log)
        result.steps = list(log.steps)
        (save or store.put_listing)(result)
    log.add("done", "Done")
    return result


async def run_litter(
    members: list[Animal],
    location: Location,
    *,
    qloo: QlooClient,
    store: Store,
    seeds: Seeds,
    model_factory: ModelFactory | None,
    log: StepLog,
    output_mode: str = "native",
    force: bool = False,
    classifier: JevClassifier | None = None,
    fallbacks: Fallbacks = (),
) -> list[ListingResult]:
    """A litter named as a set. The first member's names all come from one title, which
    becomes the litter's; the others draw from it without repeating a name.

    Members already saved are kept and their title followed, so naming the litter again
    only fills the gaps. `force` rewrites every member (the examples script only).
    """
    profile = await get_profile(
        members[0],
        location,
        qloo=qloo,
        store=store,
        seeds=seeds,
        model_factory=model_factory,
        log=log,
        output_mode=output_mode,
        classifier=classifier,
        fallbacks=fallbacks,
    )
    ids = {m.id for m in members}
    results: list[ListingResult] = []
    # The area's steps belong to every member's result; each member's own steps only to
    # its own (review of PR #45: member N showed members 1 to N-1's steps too).
    shared_steps = len(log.steps)
    async with _listing_locks[(id(asyncio.get_running_loop()), location.id)]:
        if force:
            for m in members:
                store.delete_listing(m.id, location.id)
        theme = litter_theme(location, store, ids)
        for i, animal in enumerate(members, 1):
            saved = store.get_listing(animal.id, location.id)
            if saved is not None:
                log.add("note", f"Litter member {i} of {len(members)} is already named")
                results.append(saved)
                continue
            own_steps = len(log.steps)
            log.add("start", f"Litter member {i} of {len(members)}")
            result = await write_listing(
                animal,
                location,
                profile,
                model_factory=model_factory,
                log=log,
                output_mode=output_mode,
                taken=taken_names(animal, location, store),
                taken_refs=taken_references(animal, location, store),
                theme=theme,
                first_of_litter=theme is None,
                fallbacks=fallbacks,
            )
            if result.draft is not None and theme is None:
                theme = result.draft.names[0].entity_id
                title = next(
                    e.name for e in profile.pet_entities + profile.local_tastes if e.id == theme
                )
                log.add("decision", f"The litter's names will all come from {title}")
            await asyncio.to_thread(add_audiences, result, qloo, log)
            result.steps = log.steps[:shared_steps] + log.steps[own_steps:]
            store.put_listing(result)
            results.append(result)
    log.add("done", "Done")
    return results
