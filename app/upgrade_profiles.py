"""Bring saved location profiles up to the current version (decision 18), keeping what
Namesake's AI chose: the titles, their order, the venues and its reasons for them.

    python -m app.upgrade_profiles [--only park-slope,astoria]

Only the parts that changed are asked of Qloo again: the area's top shows (usually
cached), the baseline shows' venues, and the heatmaps for the map layer. Listings and
names stay valid, since the titles do not change. A profile is saved only when the new
version is complete; one Qloo could not finish (the key is rate-limited) stays as it was,
and a later run picks it up. Run it with QLOO_MIN_INTERVAL raised (100 seconds is about
12 calls in 20 minutes) so it keeps under the key's limit.
"""

import argparse

from app.config import get_settings
from app.locations import Location, load_locations
from app.profile import (
    PROFILE_VERSION,
    LocationProfile,
    baseline_from_tastes,
    local_tastes,
    profile_from,
)
from app.qloo.exec import QlooClient
from app.runs import qloo_client
from app.store import Store


def upgrade(old: LocationProfile, location: Location, qloo: QlooClient) -> LocationProfile | None:
    """The profile at the current version, or None when Qloo could not complete it."""
    tastes = old.local_tastes or local_tastes(qloo, location)
    baselines = baseline_from_tastes(tastes, old.pet_entities)
    new = profile_from(qloo, location, old.pet_entities, baselines, old.venue_signals or None)
    if not new.complete:
        return None
    # What the AI chose and why, as it was.
    reasons = {v.entity_id: (v.chosen_reason, v.rejected_reason) for v in old.venues}
    for venue in new.venues:
        venue.chosen_reason, venue.rejected_reason = reasons.get(venue.entity_id, (None, None))
    new.species = old.species
    new.made_by = old.made_by
    new.order_source = old.order_source
    new.ranked = old.ranked
    new.local_tastes = tastes
    return new


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="location IDs, comma-separated")
    args = parser.parse_args()
    settings = get_settings()
    store = Store(settings.cache_db)
    qloo = qloo_client(settings)
    presets = {loc.id: loc for loc in load_locations(settings.locations_file)}
    wanted = [x for x in args.only.split(",") if x]
    # The presets first, in their order, then areas visitors typed.
    order = list(presets) + sorted({loc for loc, _ in store.saved_profiles()} - set(presets))
    for location_id in order:
        if wanted and location_id not in wanted:
            continue
        location = presets.get(location_id) or store.get_location(location_id)
        for loc_id, species in store.saved_profiles():
            if loc_id != location_id or location is None:
                continue
            old = store.get_profile(loc_id, species)
            if old is None or old.version >= PROFILE_VERSION:
                continue
            new = upgrade(old, location, qloo)
            if new is None:
                print(f"{loc_id} {species}: not complete yet; left as it was")
                continue
            store.put_profile(new)
            print(f"{loc_id} {species}: upgraded ({len(new.cells)} map cells)")


if __name__ == "__main__":
    main()
