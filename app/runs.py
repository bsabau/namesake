"""Agent runs started from the web: one background task and one step log each.

Runs live in memory; shared results are saved in the store, so the result page
survives a restart. A run whose result is already saved finishes at once without
calling the model or Qloo. Anything else is live work and is counted against the
limits in `app/limits.py` before it starts.

A refined listing, and any listing for an animal a visitor added, belongs to that
visitor's session and is never saved to the store.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from app.agent.model import ModelNotConfigured, build_model
from app.agent.pipeline import run_litter, run_pipeline
from app.agent.results import ListingResult
from app.agent.steps import StepLog
from app.animals import Animal, LitterPhoto, load_roster
from app.config import Settings
from app.limits import Limits
from app.locations import Location
from app.profile import load_seeds
from app.qloo.cache import Cache
from app.qloo.exec import QlooClient, harness_env
from app.session import ADDED_PREFIX, Session
from app.store import Store


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

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def result_url(self) -> str:
        return f"/result?animal={self.animal_id}&location={self.location_id}"


RUNS: dict[str, Run] = {}


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
    except ModelNotConfigured:
        return None
    return lambda: build_model(settings, session_id=uuid.uuid4().hex)


def qloo_client(settings: Settings) -> QlooClient:
    return QlooClient(
        Cache(settings.cache_db),
        mode="live" if settings.allow_live_qloo else "replay",
        recordings=settings.qloo_recordings,
        env=harness_env(settings),
        min_interval=settings.qloo_min_interval,
    )


def live_work_possible(settings: Settings) -> bool:
    """Whether a run can reach a model or Qloo; without either it is a free fallback."""
    return settings.allow_live_qloo or model_factory(settings) is not None


def charge(settings: Settings, visitor: str) -> None:
    if live_work_possible(settings):
        limits_for(settings).charge(visitor, "run")


def _new_run(animal_id: str, location_id: str, session_id: str | None = None) -> Run:
    run = Run(
        id=uuid.uuid4().hex[:12],
        animal_id=animal_id,
        location_id=location_id,
        log=StepLog(asyncio.get_running_loop()),
        session_id=session_id,
    )
    RUNS[run.id] = run
    return run


def _saved(run: Run) -> Run:
    run.log.add("note", "This listing was made before; showing the saved result")
    run.log.add("done", "Done")
    run.log.finish()
    return run


def _launch(run: Run, work) -> None:
    async def go() -> None:
        try:
            await work
        except Exception as exc:  # noqa: BLE001 - shown on the Working page, never swallowed
            run.error = type(exc).__name__
            run.log.add("error", f"The run stopped: {type(exc).__name__}")
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
) -> Run:
    """One animal's listing. Raises LimitReached before starting any live work."""
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
        return _saved(_new_run(animal.id, location.id, session.id if added else None))

    charge(settings, visitor)
    run = _new_run(animal.id, location.id, session.id if personal else None)

    def keep(result: ListingResult) -> None:
        session.listings[key] = result
        if request is None:
            session.requests.pop(key, None)
        else:
            session.requests[key] = request

    _launch(
        run,
        run_pipeline(
            animal,
            location,
            qloo=qloo_client(settings),
            store=store,
            seeds=load_seeds(settings.seeds_file),
            model_factory=model_factory(settings),
            log=run.log,
            output_mode=settings.agent_output_mode,
            litter_mates=roster_litter_mates(animal, settings),
            request=request,
            save=keep if personal else None,
        ),
    )
    return run


async def start_litter_run(
    litter: LitterPhoto, location: Location, settings: Settings, *, visitor: str = "local"
) -> Run:
    """A litter named as a set; the run ends on the first member's result."""
    roster = load_roster(settings.animals_file)
    members = [a for a in (roster.get(m) for m in litter.members) if a is not None]
    store = Store(settings.cache_db)
    if all(store.get_listing(m.id, location.id) is not None for m in members):
        return _saved(_new_run(members[0].id, location.id))

    charge(settings, visitor)
    run = _new_run(members[0].id, location.id)
    _launch(
        run,
        run_litter(
            members,
            location,
            qloo=qloo_client(settings),
            store=store,
            seeds=load_seeds(settings.seeds_file),
            model_factory=model_factory(settings),
            log=run.log,
            output_mode=settings.agent_output_mode,
        ),
    )
    return run
