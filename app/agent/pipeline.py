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

from app.agent.listing_agent import (
    ListingDeps,
    build_listing_agent,
    reference_for,
    shown_bio,
)
from app.agent.profile_agent import ProfileDeps, build_profile_agent
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.animals import ADDED_PREFIX, Animal
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
    profile_from,
)
from app.qloo.exec import QlooClient
from app.store import Store

# Bounds on one agent run: model requests and tool calls.
PROFILE_LIMITS = UsageLimits(request_limit=16, tool_calls_limit=14)
LISTING_LIMITS = UsageLimits(request_limit=6, tool_calls_limit=4)

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
    prepared: Prepared,
) -> LocationProfile:
    # The baseline was fixed before the AI runs (`_build_profile`), so its venue choices
    # are judged against the same comparison the page shows.
    tastes, baselines, source, notes = prepared
    base_ids = None
    if baselines:
        log.add("qloo", f"Baseline: places near {location.label} for fans of its top shows")
        base_ids = await asyncio.to_thread(baseline_venue_ids, qloo, location, baselines)

    deps = ProfileDeps(
        qloo=qloo,
        location=location,
        species=species,
        log=log,
        baseline_venues=base_ids,
        baseline_titles={e.id: e.name for e in baselines},
    )
    agent = build_profile_agent(model, output_mode)
    prompt = "Build the profile."
    if baselines:
        # Said up front, so no lookup or repair round is spent on them.
        names = " and ".join(e.name for e in baselines)
        what = "this area's top shows" if source == "area" else "the show used"
        them = "them" if len(baselines) > 1 else "it"
        prompt += f" {names}: {what} for the comparison; do not propose {them} as pet titles."
    run = await agent.run(prompt, deps=deps, usage_limits=PROFILE_LIMITS)
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
        profile_from, qloo, location, pets, baselines, deps.venue_signals
    )
    profile.local_tastes, profile.baseline_source = tastes, source
    profile.notes = notes + profile.notes
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
        if saved is not None and saved.version >= PROFILE_VERSION and not saved.complete:
            # Saved unfinished: finish it around the same titles, so listings made from it
            # keep their evidence. Fixed calls only; what is cached costs nothing.
            log.add("qloo", f"Finishing the saved profile for {species}s in {location.label}")
            finished = await asyncio.to_thread(finish_profile, saved, location, qloo, seeds)
            if finished is not None:
                store.put_profile(finished)
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
    log.add("start", f"Building the profile for {species}s in {location.label}")
    # The baseline is what the area watches most, leaving out shows that mention animals
    # (decision 18): looked up once here, for the AI's run and the fallback alike. The step
    # log names no title: the Why panel does.
    log.add("qloo", f"Looking up what people around {location.label} tend to watch")
    prepared = await asyncio.to_thread(baseline_for, qloo, location, seeds)

    profile = None
    if model_factory is not None:
        try:
            profile = await agent_profile(
                qloo, location, species, seeds, model_factory(), log, output_mode, prepared
            )
        except AGENT_FAILURES as exc:
            log.add(
                "error", f"Namesake's AI did not finish the area profile ({type(exc).__name__})"
            )
    if profile is None:
        log.add("note", "Falling back to the fixed lookup with the seed titles")
        profile = await asyncio.to_thread(build_profile, qloo, location, seeds, prepared)

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
    for other in store.listings_at(location.id):
        if other.animal_id != animal.id and other.draft is not None:
            names.add(other.draft.names[0].name.lower())
    for animal_id, approved in store.approved_names(location.id).items():
        if animal_id != animal.id and not animal_id.startswith(ADDED_PREFIX):
            names |= approved
    return frozenset(names)


def litter_theme(location: Location, store: Store, mates: set[str]) -> str | None:
    """The title a litter's saved members were named from, if any have been."""
    for mate in sorted(mates):
        saved = store.get_listing(mate, location.id)
        if saved is not None and saved.draft is not None:
            return saved.draft.names[0].entity_id
    return None


async def write_listing(
    animal: Animal,
    location: Location,
    profile: LocationProfile,
    *,
    model_factory: ModelFactory | None,
    log: StepLog,
    output_mode: str,
    taken: frozenset[str] = frozenset(),
    request: str | None = None,
    theme: str | None = None,
    first_of_litter: bool = False,
    qloo: QlooClient | None = None,
) -> ListingResult:
    """One listing. `request` is a volunteer's refine request. For a litter named as a
    set, `theme` limits the names to the litter's title, and the first member's names
    must all come from one title, which becomes the theme. With `qloo`, the agent may
    look up titles featuring an animal that looks like this one."""
    result = ListingResult(
        animal_id=animal.id, location_id=location.id, checks_version=CHECKS_VERSION
    )
    if model_factory is None:
        result.fallback_reason = "No model is configured, so this is the templated listing."
        return result
    titles: dict[str, tuple[Entity, str]] = {e.id: (e, "pet") for e in profile.pet_entities}
    for e in profile.local_tastes:
        titles.setdefault(e.id, (e, "local"))
    if theme is not None:
        titles = {k: v for k, v in titles.items() if k == theme}
    if not titles:
        result.fallback_reason = "Qloo returned no titles to draw names from."
        return result

    log.add("start", f"Writing the listing and name options for the {animal.species}")
    agent = build_listing_agent(model_factory(), output_mode)
    deps = ListingDeps(
        animal=animal,
        titles=titles,
        log=log,
        taken_names=taken,
        request=request,
        litter_title=titles[theme][0].name if theme else None,
        first_of_litter=first_of_litter,
        qloo=qloo,
    )
    try:
        # The lookup tool is synchronous and runs `qloo` as a subprocess; PydanticAI
        # runs sync tools in a worker thread.
        run = await agent.run("Write the listing.", deps=deps, usage_limits=LISTING_LIMITS)
        result.draft = run.output
        result.bio = shown_bio(animal, run.output)
        # deps.titles now includes any lookalike titles the agent found.
        result.references = [
            reference_for(o, deps.titles[o.entity_id][0].name) for o in run.output.names
        ]
        result.hook = f"Named after {result.references[0]}."
        used = {o.entity_id for o in run.output.names}
        result.lookalikes = [v for k, v in deps.lookalikes.items() if k in used]
    except AGENT_FAILURES as exc:
        log.add("error", f"The listing did not pass its checks ({type(exc).__name__})")
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
            request=request,
            # A litter member written on its own keeps to the title its mates share,
            # or, as the first one named, takes all its names from one title.
            theme=theme,
            first_of_litter=bool(litter_mates) and theme is None,
            qloo=qloo,
        )
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
    )
    ids = {m.id for m in members}
    results: list[ListingResult] = []
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
            log.add("start", f"Litter member {i} of {len(members)}")
            result = await write_listing(
                animal,
                location,
                profile,
                model_factory=model_factory,
                log=log,
                output_mode=output_mode,
                taken=taken_names(animal, location, store),
                theme=theme,
                first_of_litter=theme is None,
            )
            if result.draft is not None and theme is None:
                theme = result.draft.names[0].entity_id
                title = next(
                    e.name for e in profile.pet_entities + profile.local_tastes if e.id == theme
                )
                log.add("decision", f"The litter's names will all come from {title}")
            result.steps = list(log.steps)
            store.put_listing(result)
            results.append(result)
    log.add("done", "Done")
    return results
