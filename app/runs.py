"""Agent runs started from the web: one background task and one step log each.

Runs live in memory; shared results are saved in the store, so the result page
survives a restart. A run whose result is already saved finishes at once without
calling the model or Qloo. Anything else is live work and is counted against the
limits in `app/limits.py` before it starts.

A refined listing, and any listing for an animal a visitor added, belongs to that
visitor's session and is never saved to the store.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from app.agent.model import ModelMisconfigured, ModelNotConfigured, build_model, fallback_models
from app.agent.pipeline import run_litter, run_pipeline
from app.agent.results import ListingResult
from app.agent.steps import StepLog
from app.animals import Animal, LitterPhoto, load_roster
from app.classify import classifier_from
from app.config import Settings
from app.custom_location import UNAVAILABLE, LocationCheck, check_location, location_id
from app.limits import LimitReached, Limits
from app.locations import Location
from app.places import MAX_PIN_KM, places_for
from app.profile import load_seeds
from app.qloo.cache import Cache
from app.qloo.exec import QlooClient, harness_env
from app.session import ADDED_PREFIX, SESSIONS, Session
from app.store import Store
from app.venue_points import locate_saved

logger = logging.getLogger(__name__)


@dataclass
class AreaCheck:
    """A typed area checked with Qloo as a run's first step (decision 32): what the
    visitor sent, so the working page can offer Qloo's candidates or another try."""

    text: str
    # The animal or litter picked, as posted, to start again with a candidate.
    picked: str
    pin: tuple[float, float] | None = None
    # Set when the check did not pass.
    outcome: LocationCheck | None = None


@dataclass
class Run:
    id: str
    animal_id: str
    location_id: str
    log: StepLog
    task: asyncio.Task | None = None
    error: str | None = field(default=None)
    # The visitor's session, for runs over an added animal or a refined listing.
    session_id: str | None = None
    # A typed area not checked before: the check, and the area as typed until it passes.
    area: AreaCheck | None = None
    place: Location | None = None

    @property
    def area_failed(self) -> bool:
        return self.area is not None and self.area.outcome is not None

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def result_url(self) -> str:
        return f"/result?animal={self.animal_id}&location={self.location_id}"


RUNS: dict[str, Run] = {}
# Said in the run when the visitor's spot is too far from the area Qloo checked.
FAR_PIN = (
    f"The spot you picked is more than {MAX_PIN_KM} km from Qloo's data for this area, so "
    "the maps leave it out"
)
# Runs are kept in memory for their Working page and its stream: finished ones for an
# hour, and never more than this many in all (19 October audit: a bot could grow the
# list without end). A run still working is never dropped.
RUN_TTL = 3600.0
MAX_RUNS = 300


def prune_runs(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    # An hour from when the run finished, not when it started: a slow run's page stays.
    old = [
        i for i, r in RUNS.items() if r.log.finished and (r.log.finished_at or 0) < now - RUN_TTL
    ]
    for run_id in old:
        del RUNS[run_id]
    finished = [i for i, r in RUNS.items() if r.log.finished]
    while len(RUNS) > MAX_RUNS and finished:
        del RUNS[finished.pop(0)]


@cache
def _limits(db: Path, per_visitor: int, per_day: int, locations: int) -> Limits:
    return Limits(
        db, per_visitor_per_hour=per_visitor, runs_per_day=per_day, locations_per_day=locations
    )


def limits_for(settings: Settings) -> Limits:
    return _limits(
        settings.cache_db,
        settings.live_runs_per_visitor_per_hour,
        settings.live_runs_per_day,
        settings.new_locations_per_day,
    )


def roster_litter_mates(animal: Animal, settings: Settings) -> set[str]:
    """The other members of the animal's litter, who may share a naming theme."""
    if animal.litter is None:
        return set()
    roster = load_roster(settings.animals_file)
    return {a.id for a in roster.animals if a.litter == animal.litter and a.id != animal.id}


def model_factory(settings: Settings):
    try:
        build_model(settings)
    except ModelMisconfigured as exc:
        # Filled in but wrong: say so, or every run would quietly go to the paid fallback.
        logger.error("the main model is skipped: %s", exc)
        return None
    except ModelNotConfigured:
        return None
    return lambda: build_model(settings, session_id=uuid.uuid4().hex)


def replay_client(settings: Settings) -> QlooClient:
    """The cache and recordings only: never a live call."""
    return QlooClient(
        Cache(settings.cache_db), mode="replay", recordings=settings.qloo_recordings, env={}
    )


def qloo_client(settings: Settings) -> QlooClient:
    return QlooClient(
        Cache(settings.cache_db),
        mode="live" if settings.allow_live_qloo else "replay",
        recordings=settings.qloo_recordings,
        env=harness_env(settings),
        min_interval=settings.qloo_min_interval,
    )


def visit_names(
    session: Session | None, animal_id: str, location_id: str, store: Store
) -> frozenset[str]:
    """Names this visitor has given other animals here: the first names of their own
    listings, and names they approved for animals they added."""
    if session is None:
        return frozenset()
    names = set()
    for key, listing in session.listings.items():
        other, _, place = key.partition("@")
        if other != animal_id and place == location_id and listing.draft is not None:
            names.add(listing.draft.names[0].name.lower())
    approved = store.approved_names(location_id)
    for other in session.animals:
        if other != animal_id:
            names |= approved.get(other, set())
    return frozenset(names)


def live_work_possible(settings: Settings) -> bool:
    """Whether a run can reach a model or Qloo; without either it is a free fallback."""
    return (
        settings.allow_live_qloo
        or model_factory(settings) is not None
        or bool(fallback_models(settings))
    )


def charge(settings: Settings, visitor: str) -> None:
    if live_work_possible(settings):
        limits_for(settings).charge(visitor, "run")


def refund(settings: Settings, visitor: str) -> None:
    if live_work_possible(settings):
        limits_for(settings).refund(visitor, "run")


def check_area(settings: Settings, text: str, visitor: str) -> LocationCheck:
    """A typed area checked with Qloo: from the cache and recordings first, since an
    answer Qloo gave before is free, then live, counted against the new-areas cap."""
    seeds = load_seeds(settings.seeds_file)
    checked = check_location(replay_client(settings), text, seeds)
    if checked.status != "unavailable" or not settings.allow_live_qloo:
        return checked
    limits = limits_for(settings)
    try:
        # Reserved before the call, so two checks at once cannot both pass the cap.
        limits.charge(visitor, "location")
    except LimitReached as exc:
        return LocationCheck(status="unavailable", message=str(exc))
    qloo = qloo_client(settings)
    checked = check_location(qloo, text, seeds)
    if not getattr(qloo, "live_calls", 0):
        limits.refund(visitor, "location")
    return checked


def _new_run(animal_id: str, location_id: str, session_id: str | None = None) -> Run:
    run = Run(
        id=uuid.uuid4().hex[:12],
        animal_id=animal_id,
        location_id=location_id,
        log=StepLog(asyncio.get_running_loop()),
        session_id=session_id,
    )
    prune_runs()
    RUNS[run.id] = run
    return run


def _saved(run: Run, note: str | None = None) -> Run:
    if note:
        run.log.add("note", note)
    run.log.add("note", "This listing was made before; showing the saved result")
    run.log.add("done", "Done")
    run.log.finish()
    return run


def _launch(run: Run, work, then=None) -> None:
    async def go() -> None:
        try:
            await work
            if then is not None and not run.failed:
                try:
                    await asyncio.to_thread(then)
                except Exception as exc:  # noqa: BLE001 - the result is saved; only pins wait
                    logger.warning("run %s: pinning failed (%s)", run.id, type(exc).__name__)
                    run.log.add("note", "The places could not be pinned yet")
        except Exception:  # noqa: BLE001 - shown on the Working page, never swallowed
            # The visitor reads the step and the stream; the exception is for the server's
            # log only.
            run.error = "RunStopped"
            logger.exception("run %s stopped", run.id)
            run.log.add("error", "The run stopped on an error in Namesake's code")
        finally:
            # After any error is logged, so a follower always sees it before the end.
            run.log.finish()

    run.task = asyncio.create_task(go())


async def start_run(
    animal: Animal,
    location: Location,
    settings: Settings,
    *,
    visitor: str = "local",
    session: Session | None = None,
    request: str | None = None,
    note: str | None = None,
) -> Run:
    """One animal's listing, with `note` as its first step when given. Raises
    LimitReached before starting any live work."""
    store = Store(settings.cache_db)
    added = animal.id.startswith(ADDED_PREFIX)
    personal = added or request is not None
    if personal and session is None:
        raise ValueError("a refined listing or an added animal needs the visitor's session")
    key = f"{animal.id}@{location.id}"
    if request is None and (
        (added and key in session.listings)
        or (not added and store.get_listing(animal.id, location.id) is not None)
    ):
        return _saved(_new_run(animal.id, location.id, session.id if added else None), note)

    charge(settings, visitor)
    run = _new_run(animal.id, location.id, session.id if personal else None)
    if note:
        run.log.add("note", note)
    _launch(
        run,
        _listing_work(animal, location, settings, run, session, request),
        then=lambda: locate_saved(
            store, location, animal.species, places_for(settings.geocoder_url), run.log
        ),
    )
    return run


def _listing_work(
    animal: Animal,
    location: Location,
    settings: Settings,
    run: Run,
    session: Session | None,
    request: str | None = None,
):
    """The pipeline for one animal's listing, writing to the run's log."""
    store = Store(settings.cache_db)
    personal = animal.id.startswith(ADDED_PREFIX) or request is not None
    key = f"{animal.id}@{location.id}"

    def keep(result: ListingResult) -> None:
        if animal.id.startswith(ADDED_PREFIX) and session.animals.get(animal.id) != animal:
            # Removed or edited while the run worked: this listing describes a record the
            # workspace no longer holds, so it is not kept (review of the workspace PR).
            return
        session.listings[key] = result
        if request is None:
            session.requests.pop(key, None)
        else:
            session.requests[key] = request
        SESSIONS.save(session)

    return run_pipeline(
        animal,
        location,
        qloo=qloo_client(settings),
        store=store,
        seeds=load_seeds(settings.seeds_file),
        model_factory=model_factory(settings),
        fallbacks=fallback_models(settings),
        log=run.log,
        output_mode=settings.agent_output_mode,
        classifier=classifier_from(settings),
        litter_mates=roster_litter_mates(animal, settings),
        request=request,
        save=keep if personal else None,
        # A visit's own names bind only its own listings, never a shared one.
        also_taken=visit_names(session, animal.id, location.id, store) if personal else frozenset(),
    )


async def start_litter_run(
    litter: LitterPhoto,
    location: Location,
    settings: Settings,
    *,
    visitor: str = "local",
    note: str | None = None,
) -> Run:
    """A litter named as a set; the run ends on the first member's result."""
    members = litter_members(litter, settings)
    store = Store(settings.cache_db)
    if all(store.get_listing(m.id, location.id) is not None for m in members):
        return _saved(_new_run(members[0].id, location.id), note)

    charge(settings, visitor)
    run = _new_run(members[0].id, location.id)
    if note:
        run.log.add("note", note)
    _launch(
        run,
        _litter_work(members, location, settings, run),
        then=lambda: locate_saved(
            store, location, members[0].species, places_for(settings.geocoder_url), run.log
        ),
    )
    return run


def litter_members(litter: LitterPhoto, settings: Settings) -> list[Animal]:
    roster = load_roster(settings.animals_file)
    return [a for a in (roster.get(m) for m in litter.members) if a is not None]


def _litter_work(members: list[Animal], location: Location, settings: Settings, run: Run):
    return run_litter(
        members,
        location,
        qloo=qloo_client(settings),
        store=Store(settings.cache_db),
        seeds=load_seeds(settings.seeds_file),
        model_factory=model_factory(settings),
        fallbacks=fallback_models(settings),
        log=run.log,
        output_mode=settings.agent_output_mode,
        classifier=classifier_from(settings),
    )


async def start_area_run(
    text: str,
    picked: str,
    settings: Settings,
    *,
    animal: Animal | None = None,
    litter: LitterPhoto | None = None,
    pin: tuple[float, float] | None = None,
    keep_pin: Callable[[Location], bool] = lambda _: True,
    visitor: str = "local",
    session: Session | None = None,
) -> Run:
    """A run over a typed area not checked before (decision 32): its first step checks
    the area with Qloo; when that passes, the area is saved and offered like a preset, and
    the listing (or the litter's) follows in the same run. When it does not, the run ends
    with Qloo's answer, which the working page shows with its candidates. `text` is the
    cleaned name; `keep_pin` keeps the visitor's spot for the area and says whether it
    was close enough. Raises LimitReached before starting any live work."""
    members = litter_members(litter, settings) if litter is not None else []
    first = members[0] if members else animal
    if first is None:
        raise ValueError("an area run needs an animal or a litter")
    personal = first.id.startswith(ADDED_PREFIX)
    if (personal or pin is not None) and session is None:
        raise ValueError("an added animal or a picked spot needs the visitor's session")
    charge(settings, visitor)
    # A run carrying the visitor's spot is theirs alone: its page offers the spot back.
    owner = session.id if personal or pin is not None else None
    run = _new_run(first.id, location_id(text), owner)
    run.area = AreaCheck(text=text, picked=picked, pin=pin)
    # Shown until the check passes: the name as typed, with no map of its own yet.
    run.place = Location(
        id=run.location_id, label=text, region="", query=text, city=text, latitude=0,
        longitude=0,
    )  # fmt: skip
    store = Store(settings.cache_db)

    async def work() -> None:
        run.log.add(
            "qloo",
            f"Checking “{text}” with Qloo: the TV show it ranks highest there, and where that "
            "show's fans are within it",
        )
        try:
            checked = await asyncio.to_thread(check_area, settings, text, visitor)
        except Exception:  # noqa: BLE001 - an answer the check could not read: try again later
            logger.exception("the area check failed")
            checked = LocationCheck(status="unavailable", message=UNAVAILABLE)
        if checked.status != "ok" or checked.location is None:
            run.area.outcome = checked
            run.error = "AreaNotChecked"
            refund(settings, visitor)
            run.log.add("error", f"The check of “{text}” did not pass, so no listing was written")
            return
        store.put_location(checked.location)
        run.place = checked.location
        run.log.add("check", f"Qloo has enough data for “{text}”; it is saved as an area")
        if pin is not None and not keep_pin(checked.location):
            run.log.add("note", FAR_PIN)
        if members:
            await _litter_work(members, checked.location, settings, run)
        else:
            await _listing_work(first, checked.location, settings, run, session)

    _launch(
        run,
        work(),
        then=lambda: locate_saved(
            store, run.place, first.species, places_for(settings.geocoder_url), run.log
        ),
    )
    return run
