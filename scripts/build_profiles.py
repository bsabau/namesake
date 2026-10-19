"""Build the location profile for every preset location and print a summary.

    uv run python scripts/build_profiles.py          # from the cache and recordings only
    uv run python scripts/build_profiles.py --live   # call Qloo for anything missing

Live calls are cached and recorded under `var/`, so the web app can serve the
profiles without calling Qloo.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.locations import load_locations  # noqa: E402
from app.profile import baseline_titles, build_profile, load_seeds  # noqa: E402
from app.qloo.cache import Cache  # noqa: E402
from app.qloo.exec import QlooClient, harness_env  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--location", help="only this preset id")
    args = parser.parse_args()
    settings = get_settings()
    qloo = QlooClient(
        Cache(settings.cache_db),
        mode="live" if args.live else "replay",
        recordings=settings.qloo_recordings,
        env=harness_env(settings),
        min_interval=settings.qloo_min_interval,
    )
    seeds = load_seeds(settings.seeds_file)
    for location in load_locations(settings.locations_file):
        if args.location and location.id != args.location:
            continue
        # Species-agnostic: a dog's or a cat's run asks its venues with its own titles
        # first (decision 26), so those cache keys are filled by the runs themselves.
        p = build_profile(qloo, location, seeds)
        print(f"\n## {location.label}  complete={p.complete}")
        print("   pet:", [f"{e.name} ({e.resolution})" for e in p.pet_entities])
        print("   baseline:", [e.name for e in baseline_titles(p)])
        for v in p.venues:
            flag = "distinctive" if v.distinctive else f"baseline #{v.baseline_rank}"
            bad = f"  UNSUITABLE: {v.unsuitable}" if v.unsuitable else ""
            print(f"   {v.rank:2} {v.name} [{flag}] {v.neighbourhood}{bad}")
        lifts = [c.lift for c in p.cells if c.lift is not None]
        print(f"   cells: {len(p.cells)}, with lift: {len(lifts)}")
        for n in p.notes:
            print(f"   note: {n}")
    print(f"\nlive calls: {qloo.live_calls}")


if __name__ == "__main__":
    main()
