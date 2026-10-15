"""Agent runs started from the web: one background task and one step log each.

Runs live in memory; their results are saved in the store, so the result page
survives a restart. A run for an animal and location that is already saved
finishes at once without calling the model or Qloo.
"""

import asyncio
import uuid
from dataclasses import dataclass, field

from app.agent.model import ModelNotConfigured, build_model
from app.agent.pipeline import run_pipeline
from app.agent.steps import StepLog
from app.animals import Animal
from app.config import Settings
from app.locations import Location
from app.profile import load_seeds
from app.qloo.cache import Cache
from app.qloo.exec import QlooClient, harness_env
from app.store import Store


@dataclass
class Run:
    id: str
    animal_id: str
    location_id: str
    log: StepLog
    task: asyncio.Task | None = None
    error: str | None = field(default=None)

    @property
    def result_url(self) -> str:
        return f"/result?animal={self.animal_id}&location={self.location_id}"


RUNS: dict[str, Run] = {}


def model_factory(settings: Settings):
    try:
        build_model(settings)
    except ModelNotConfigured:
        return None
    return lambda: build_model(settings, session_id=uuid.uuid4().hex)


async def start_run(animal: Animal, location: Location, settings: Settings) -> Run:
    run = Run(
        id=uuid.uuid4().hex[:12],
        animal_id=animal.id,
        location_id=location.id,
        log=StepLog(asyncio.get_running_loop()),
    )
    RUNS[run.id] = run
    store = Store(settings.cache_db)
    if store.get_listing(animal.id, location.id) is not None:
        run.log.add("note", "This listing was made before; showing the saved result")
        run.log.add("done", "Done")
        run.log.finish()
        return run

    qloo = QlooClient(
        Cache(settings.cache_db),
        mode="live" if settings.allow_live_qloo else "replay",
        recordings=settings.qloo_recordings,
        env=harness_env(settings),
        min_interval=settings.qloo_min_interval,
    )

    async def go() -> None:
        try:
            await run_pipeline(
                animal,
                location,
                qloo=qloo,
                store=store,
                seeds=load_seeds(settings.seeds_file),
                model_factory=model_factory(settings),
                log=run.log,
                output_mode=settings.agent_output_mode,
            )
        except Exception as exc:  # noqa: BLE001 - shown on the Working page, never swallowed
            run.error = type(exc).__name__
            run.log.add("error", f"The run stopped: {type(exc).__name__}")
            run.log.finish()

    run.task = asyncio.create_task(go())
    return run
