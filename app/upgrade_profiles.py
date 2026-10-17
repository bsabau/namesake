"""Bring saved location profiles up to the current version (decision 18), keeping what
Namesake's AI chose: the titles, their order, the venues and its reasons for them.

    python -m app.upgrade_profiles [--only park-slope,astoria] [--min-interval 10]

Only the parts that changed are asked of Qloo again (`finish_profile`): the area's top
shows (usually cached), the baseline shows' venues, and the heatmaps for the map layer,
about 5 calls a profile. Listings and names stay valid, since the titles do not change. A
profile is saved only when the new version is complete; one Qloo could not finish (the
key is rate-limited) stays as it was, and a later run picks it up, as it does any current
profile that is not complete.

The key was refused after about 12 calls in 20 minutes on 15 October, but took 30 calls
10 seconds apart on 17 October, so calls are spaced at least --min-interval seconds (10
by default) whatever QLOO_MIN_INTERVAL says; raise it if Qloo refuses, and split a long
run with --only.
"""

import argparse

from app.config import get_settings
from app.locations import load_locations
from app.profile import finish_profile, load_seeds, needs_finishing
from app.runs import qloo_client
from app.store import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="location IDs, comma-separated")
    parser.add_argument("--min-interval", type=float, default=10.0)
    args = parser.parse_args()
    settings = get_settings()
    settings.qloo_min_interval = max(settings.qloo_min_interval, args.min_interval)
    store = Store(settings.cache_db)
    qloo = qloo_client(settings)
    seeds = load_seeds(settings.seeds_file)
    presets = {loc.id: loc for loc in load_locations(settings.locations_file)}
    wanted = [x for x in args.only.split(",") if x]
    saved = store.saved_profiles()
    # The presets first, in their order, then areas visitors typed.
    order = list(presets) + sorted({loc for loc, _ in saved} - set(presets))
    for location_id in order:
        if wanted and location_id not in wanted:
            continue
        location = presets.get(location_id) or store.get_location(location_id)
        for loc_id, species in saved:
            if loc_id != location_id:
                continue
            if location is None:
                print(f"{loc_id} {species}: its area is no longer saved; skipped")
                continue
            old = store.get_profile(loc_id, species)
            if old is None or not needs_finishing(old):
                continue
            new = finish_profile(old, location, qloo, seeds)
            if new is None:
                print(f"{loc_id} {species}: not complete yet; left as it was")
                continue
            store.put_profile(new)
            print(f"{loc_id} {species}: upgraded ({len(new.cells)} map cells)")


if __name__ == "__main__":
    main()
