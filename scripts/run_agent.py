"""Run the agent for one animal and location from the command line, live.

    uv run python scripts/run_agent.py dog-02 park-slope
    uv run python scripts/run_agent.py dog-02 park-slope --fresh   # rebuild the saved profile
    uv run python scripts/run_agent.py dog-02 park-slope --model 1 # only fallback 1

Qloo calls are cached, recorded and spaced; the model is the one in AGENT_*, then its
fallbacks. Each run's model usage is printed.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.model import build_model, fallback_models  # noqa: E402
from app.agent.pipeline import run_pipeline  # noqa: E402
from app.agent.steps import StepLog  # noqa: E402
from app.animals import load_roster  # noqa: E402
from app.classify import classifier_from  # noqa: E402
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
    parser.add_argument(
        "--model", choices=["main", "1", "2"], help="use only this model: main, or fallback 1 or 2"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("app.agent.pipeline").setLevel(logging.INFO)
    settings = get_settings()
    fallbacks = fallback_models(settings)
    main_model = lambda: build_model(settings)  # noqa: E731
    if args.model in ("1", "2"):
        configured = getattr(settings, f"agent_fallback_{args.model}_model")
        if configured is None:
            sys.exit(f"Fallback {args.model} is not configured.")
        # fallback_models skips unconfigured ones, so fallback 2 alone sits at index 0
        index = 0 if args.model == "1" or len(fallbacks) == 1 else 1
        main_model, fallbacks = None, (fallbacks[index],)
    elif args.model == "main":
        fallbacks = ()
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

    def echo(kind, text, **kwargs):
        print(f"[{kind}] {text}", flush=True)
        return original_add(kind, text, **kwargs)

    log.add = echo
    try:
        result = await run_pipeline(
            animal,
            location,
            qloo=qloo,
            store=store,
            seeds=load_seeds(settings.seeds_file),
            model_factory=main_model,
            log=log,
            output_mode=settings.agent_output_mode,
            fallbacks=fallbacks,
            classifier=classifier_from(settings),
        )
    finally:
        log.finish()
    print("\nfallback:", result.fallback_reason)
    if result.draft:
        for n, ref in zip(result.draft.names, result.references, strict=True):
            print(f"  name: {n.name} ({n.source}) — {ref} — {n.why}")
        print("  bio:", " ".join(s.text for s in result.bio))
        print("  hook:", result.hook)
    print(f"live Qloo calls: {qloo.live_calls}")


if __name__ == "__main__":
    asyncio.run(main())
