"""Run the agent for one animal and location from the command line, live.

    uv run python scripts/run_agent.py dog-02 park-slope
    uv run python scripts/run_agent.py dog-02 park-slope --fresh   # rebuild the saved profile

Qloo calls are cached, recorded and spaced; the model is the one in AGENT_*.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.model import build_model  # noqa: E402
from app.agent.pipeline import run_pipeline  # noqa: E402
from app.agent.steps import StepLog  # noqa: E402
from app.animals import load_roster  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.locations import load_locations  # noqa: E402
from app.profile import load_seeds  # noqa: E402
from app.qloo.cache import Cache  # noqa: E402
from app.qloo.exec import QlooClient, harness_env  # noqa: E402
from app.store import Store  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("animal")
    parser.add_argument("location")
    parser.add_argument("--fresh", action="store_true", help="ignore the saved profile")
    args = parser.parse_args()
    settings = get_settings()
    animal = load_roster(settings.animals_file).get(args.animal)
    location = next(x for x in load_locations(settings.locations_file) if x.id == args.location)
    qloo = QlooClient(
        Cache(settings.cache_db),
        recordings=settings.qloo_recordings,
        env=harness_env(settings),
        min_interval=settings.qloo_min_interval,
    )
    store = Store(settings.cache_db)
    if args.fresh:
        import sqlite3

        with sqlite3.connect(settings.cache_db) as db:
            db.execute(
                "DELETE FROM agent_results WHERE key = ?",
                (f"profile:{location.id}:{animal.species}",),
            )
    log = StepLog()
    original_add = log.add

    def echo(kind, text):
        print(f"[{kind}] {text}", flush=True)
        return original_add(kind, text)

    log.add = echo
    result = await run_pipeline(
        animal,
        location,
        qloo=qloo,
        store=store,
        seeds=load_seeds(settings.seeds_file),
        model_factory=lambda: build_model(settings),
        log=log,
        output_mode=settings.agent_output_mode,
    )
    print("\nfallback:", result.fallback_reason)
    if result.draft:
        for n in result.draft.names:
            print(f"  name: {n.name} ({n.source}) — {n.reference} — {n.why}")
        print("  bio:", " ".join(s.text for s in result.draft.bio))
        print("  hook:", result.draft.hook.text)
    print(f"live Qloo calls: {qloo.live_calls}")


if __name__ == "__main__":
    asyncio.run(main())
