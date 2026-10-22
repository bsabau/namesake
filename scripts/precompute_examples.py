"""Build the start page's examples into the cache database, live.

    uv run python scripts/precompute_examples.py            # only what is missing
    uv run python scripts/precompute_examples.py --force    # rewrite the listings
    uv run python scripts/precompute_examples.py --only astoria   # one area's examples
    uv run python scripts/precompute_examples.py --all      # every preset animal, every area
    uv run python scripts/precompute_examples.py --all --dry-run   # what --all would build

The examples are `EXAMPLES` in `app/views/build.py`: `dog-02` and `cat-01`, each in
Park Slope and Astoria. `--all` builds every animal in the roster, each litter named as
a set, in every preset area (or those in `--only`), so judges open saved listings
instead of waiting for a live run.
The results hold Qloo data and model output, so they stay in `var/`, which is never committed; the
deployed demo gets them on its private volume. Qloo calls are cached, recorded and
spaced; the model is the one in AGENT_*.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.model import fallback_models  # noqa: E402
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
from app.views.build import EXAMPLES  # noqa: E402


def kittens_of(roster, animal):
    """The members of `animal`'s litter, in the litter photo's order."""
    litter = next((lit for lit in roster.litters if animal.id in lit.members), None)
    mates = [roster.get(m) for m in litter.members] if litter else []
    if not mates or None in mates:
        sys.exit(f"{animal.id}: its litter is not in the roster as a set")
    return mates


def plan(roster, places, every: bool, only: set[str]) -> list[tuple[str, str, str]]:
    """What to build, as (animal ID, area ID, label): the examples first, so they keep
    the names they have; with `every`, then each other animal in each preset area, a
    litter once (it is named as a set). `only` keeps those areas."""
    jobs = list(EXAMPLES)
    if every:
        # A litter is keyed by its first member, whichever member an example names.
        def key(animal_id, location_id):
            animal = roster.get(animal_id)
            first = kittens_of(roster, animal)[0].id if animal and animal.litter else animal_id
            return first, location_id

        listed = {key(a, loc) for a, loc, _ in jobs}
        for location_id, location in places.items():
            for animal in roster.animals:
                if key(animal.id, location_id) in listed:
                    continue
                listed.add(key(animal.id, location_id))
                who = "the litter" if animal.litter else animal.id
                jobs.append((animal.id, location_id, f"{who} in {location.label}"))
    return [job for job in jobs if not only or job[1] in only]


def echo_log() -> StepLog:
    log = StepLog()
    original = log.add

    def echo(kind, text, **kwargs):
        print(f"  [{kind}] {text}", flush=True)
        return original(kind, text, **kwargs)

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
    parser.add_argument("--only", default="", help="location IDs, comma-separated")
    parser.add_argument(
        "--all", action="store_true", help="every preset animal in every preset area"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be built, and build nothing"
    )
    args = parser.parse_args()
    settings = get_settings()
    roster = load_roster(settings.animals_file)
    places = {x.id: x for x in load_locations(settings.locations_file)}
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    unknown = ({loc for _, loc, _ in EXAMPLES} | only) - places.keys()
    if unknown:
        sys.exit(f"Not a preset area: {', '.join(sorted(unknown))}")
    strangers = sorted(a for a, _, _ in EXAMPLES if roster.get(a) is None)
    if strangers:
        sys.exit(f"Not in the roster: {', '.join(strangers)}")
    jobs = plan(roster, places, args.all, only)
    store = Store(settings.cache_db)
    if args.dry_run:
        # Reads the saved listings only: no model, no Qloo, nothing written.
        for animal_id, location_id, label in jobs:
            animal = roster.get(animal_id)
            mates = kittens_of(roster, animal) if animal.litter is not None else [animal]
            missing = [m.id for m in mates if store.get_listing(m.id, location_id) is None]
            print(f"{'build' if args.force or missing else 'saved'}: {label}")
        return
    models = model_factory(settings)
    fallbacks = fallback_models(settings)
    if models is None and not fallbacks:
        sys.exit("No model is configured (AGENT_*); the examples need the agent.")
    qloo = qloo_client(settings)
    common = dict(
        qloo=qloo,
        store=store,
        seeds=load_seeds(settings.seeds_file),
        model_factory=models,
        fallbacks=fallbacks,
        output_mode=settings.agent_output_mode,
        classifier=classifier_from(settings),
    )
    built = []
    # The start page's examples (EXAMPLES in app/views/build.py): an animal in a litter
    # is built with its litter, named as a set.
    for animal_id, location_id, label in jobs:
        location = places[location_id]
        if location not in built:
            built.append(location)
        animal = roster.get(animal_id)
        if animal.litter is not None:
            mates = kittens_of(roster, animal)
            if args.force or any(store.get_listing(k.id, location.id) is None for k in mates):
                print(label)
                log = echo_log()
                for r in await run_litter(mates, location, log=log, force=args.force, **common):
                    show(r)
                log.finish()
        elif args.force or store.get_listing(animal.id, location.id) is None:
            print(label)
            log = echo_log()
            show(await run_pipeline(animal, location, log=log, **common))
            log.finish()
    # The example pages show the places as pins too (decision 4, revised): both species'
    # profiles in each example's area, as before.
    for location in built:
        for species in ("dog", "cat"):
            placed = locate_saved(store, location, species, places_for(settings.geocoder_url))
            if placed:
                print(f"{location.label} {species}s: {placed} places pinned")
    print(f"live Qloo calls: {qloo.live_calls}")


if __name__ == "__main__":
    asyncio.run(main())
