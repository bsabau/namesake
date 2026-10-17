"""Bring saved location profiles up to the current version (decision 18), keeping what
Namesake's AI chose: the titles, their order, the venues and its reasons for them.

    python -m app.upgrade_profiles [--only park-slope,astoria]

Only the parts that changed are asked of Qloo again: the area's top shows (usually
cached), the baseline shows' venues, and the heatmaps for the map layer: about 5 calls a
profile. Listings and names stay valid, since the titles do not change. A profile is
saved only when the new version is complete; one Qloo could not finish (the key is
rate-limited) stays as it was, and a later run picks it up, as it does any current
profile that is not complete.

The key is refused after about 12 calls in 20 minutes, so run it with QLOO_MIN_INTERVAL
at 120 seconds or more, and split a long run with --only.
"""

import argparse

from app.config import get_settings
from app.locations import Location, load_locations
from app.profile import (
    PROFILE_VERSION,
    LocationProfile,
    Seeds,
    baseline_for,
    load_seeds,
    profile_from,
)
from app.qloo.exec import QlooClient
from app.runs import qloo_client
from app.store import Store


def upgrade(
    old: LocationProfile, location: Location, qloo: QlooClient, seeds: Seeds
) -> LocationProfile | None:
    """The profile at the current version, or None when Qloo could not complete it."""
    tastes, baselines, source, notes = baseline_for(qloo, location, seeds)
    # A top show the AI picked as a pet title cannot also be its baseline.
    pet_ids = {e.id for e in old.pet_entities}
    baselines = [e for e in baselines if e.id not in pet_ids]
    new = profile_from(qloo, location, old.pet_entities, baselines, old.venue_signals or None)
    if not new.complete:
        return None
    new.local_tastes, new.baseline_source = tastes, source
    new.notes = notes + new.notes
    # The lookups behind the titles stay on the record; the rest was asked again.
    new.calls = [c for c in old.calls if c.operation in ("describe", "rank")] + new.calls
    # What the AI chose and why, as it was.
    reasons = {v.entity_id: (v.chosen_reason, v.rejected_reason) for v in old.venues}
    for venue in new.venues:
        venue.chosen_reason, venue.rejected_reason = reasons.get(venue.entity_id, (None, None))
    new.species = old.species
    new.made_by = old.made_by
    new.order_source = old.order_source
    new.ranked = old.ranked
    return new


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="location IDs, comma-separated")
    args = parser.parse_args()
    settings = get_settings()
    store = Store(settings.cache_db)
    qloo = qloo_client(settings)
    seeds = load_seeds(settings.seeds_file)
    presets = {loc.id: loc for loc in load_locations(settings.locations_file)}
    wanted = [x for x in args.only.split(",") if x]
    # The presets first, in their order, then areas visitors typed.
    saved = store.saved_profiles()
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
            if old is None or (old.version >= PROFILE_VERSION and old.complete):
                continue
            new = upgrade(old, location, qloo, seeds)
            if new is None:
                print(f"{loc_id} {species}: not complete yet; left as it was")
                continue
            store.put_profile(new)
            print(f"{loc_id} {species}: upgraded ({len(new.cells)} map cells)")


if __name__ == "__main__":
    main()
