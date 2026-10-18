"""Build the start page's examples into the cache database, live.

    uv run python scripts/precompute_examples.py            # only what is missing
    uv run python scripts/precompute_examples.py --force    # rewrite the listings

`dog-02` and the kitten litter, each in Park Slope and Astoria. The results hold
Qloo data and model output, so they stay in `var/`, which is never committed; the
deployed demo gets them on its private volume. Qloo calls are cached, recorded and
spaced; the model is the one in AGENT_*.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.pipeline import run_litter, run_pipeline  # noqa: E402
from app.agent.steps import StepLog  # noqa: E402
from app.animals import load_roster  # noqa: E402
from app.classify import classifier_from  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.locations import load_locations  # noqa: E402
from app.places import places_for  # noqa: E402
from app.profile import load_seeds  # noqa: E402
from app.runs import model_factory, qloo_client  # noqa: E402
from app.store import Store  # noqa: E402
from app.venue_points import locate_saved  # noqa: E402

LOCATIONS = ("park-slope", "astoria")
DOG = "dog-02"
LITTER = "litter-group"


def echo_log() -> StepLog:
    log = StepLog()
    original = log.add

    def echo(kind, text):
        print(f"  [{kind}] {text}", flush=True)
        return original(kind, text)

    log.add = echo
    return log


def show(result) -> None:
    if result.draft is None:
        print(f"  {result.animal_id}: templated ({result.fallback_reason})")
    else:
        names = ", ".join(n.name for n in result.draft.names)
        print(f"  {result.animal_id}: {names} | {result.hook}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="rewrite saved listings")
    args = parser.parse_args()
    settings = get_settings()
    models = model_factory(settings)
    if models is None:
        sys.exit("No model is configured (AGENT_*); the examples need the agent.")
    roster = load_roster(settings.animals_file)
    litter = next(lit for lit in roster.litters if lit.id == LITTER)
    kittens = [roster.get(m) for m in litter.members]
    store = Store(settings.cache_db)
    qloo = qloo_client(settings)
    seeds = load_seeds(settings.seeds_file)
    for location in (x for x in load_locations(settings.locations_file) if x.id in LOCATIONS):
        common = dict(
            qloo=qloo,
            store=store,
            seeds=seeds,
            model_factory=models,
            output_mode=settings.agent_output_mode,
            classifier=classifier_from(settings),
        )
        if args.force or store.get_listing(DOG, location.id) is None:
            print(f"{DOG} in {location.label}")
            log = echo_log()
            show(await run_pipeline(roster.get(DOG), location, log=log, **common))
            log.finish()
        if args.force or any(store.get_listing(k.id, location.id) is None for k in kittens):
            print(f"The litter in {location.label}")
            log = echo_log()
            for result in await run_litter(kittens, location, log=log, force=args.force, **common):
                show(result)
            log.finish()
        # The example pages show the places as pins too (decision 4, revised).
        for species in ("dog", "cat"):
            placed = locate_saved(store, location, species, places_for(settings.geocoder_url))
            if placed:
                print(f"{location.label} {species}s: {placed} places pinned")
    print(f"live Qloo calls: {qloo.live_calls}")


if __name__ == "__main__":
    asyncio.run(main())
