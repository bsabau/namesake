"""Points for the venues Qloo returned (decision 4, revised 18 October).

Qloo gives each venue a street address and a neighbourhood, but no coordinates. So when a
profile is saved, the venues the page may suggest are looked up once in OpenStreetMap
(Photon) by name and address, and the points are kept on the profile. Never from the
browser, never per visit: a profile is looked up once, and a venue that does not match
stays in the list without a pin.

    python -m app.venue_points [--only park-slope,astoria]   # saved profiles, once
"""

import argparse
import threading
from collections import defaultdict

from app.agent.steps import StepLog
from app.locations import Location
from app.places import LookupFailed, Places, Throttled
from app.profile import LocationProfile, Venue, carry_points
from app.store import Store

# The venues a page may show: the AI's picks, or the first suitable ones (the page shows
# five; one more covers a venue an animal's page skips).
LOCATE_LIMIT = 6
# A venue whose lookup fails this often is left without a pin.
MAX_FAILURES = 3


def to_locate(profile: LocationProfile) -> list[Venue]:
    """Suitable venues not looked up yet, in the order the page shows them: the AI's picks
    first, then those that stand out for pet-show fans, then by Qloo's rank."""
    suitable = [v for v in profile.venues if v.unsuitable is None and not v.point_tried]
    ordered = sorted(suitable, key=lambda v: (v.chosen_reason is None, not v.distinctive, v.rank))
    return ordered[:LOCATE_LIMIT]


def locate_venues(
    profile: LocationProfile,
    near: tuple[float, float],
    places: Places,
) -> int:
    """Look up the venues not yet tried; returns how many were placed. Stops quietly when
    Photon's allowance is spent: the rest are tried on a later save."""
    placed, failed_in_a_row = 0, 0
    for venue in to_locate(profile):
        try:
            point = places.venue_point(venue.name, venue.address, near)
        except Throttled:
            break  # the allowance is spent: a later save tries the rest
        except LookupFailed:
            # Not tried yet: a later save tries again, up to MAX_FAILURES times, so one
            # venue Photon cannot answer never holds up the others for good.
            venue.point_failures += 1
            venue.point_tried = venue.point_failures >= MAX_FAILURES
            failed_in_a_row += 1
            if failed_in_a_row >= 2:
                break  # Photon is down: stop asking
            continue
        failed_in_a_row = 0
        venue.point_tried = True
        if point is not None:
            venue.latitude, venue.longitude = point.latitude, point.longitude
            placed += 1
    return placed


_locks: defaultdict[tuple[str, str], threading.Lock] = defaultdict(threading.Lock)


def locate_saved(
    store: Store,
    location: Location,
    species: str,
    places: Places,
    log: StepLog | None = None,
) -> int:
    """Place a saved profile's venues, once, and save the points. One placer per profile at
    a time; the points are written onto the profile as saved at the end, so a profile
    finished meanwhile keeps its other changes. Free when done before."""
    with _locks[(location.id, species)]:
        profile = store.get_profile(location.id, species)
        if profile is None or not places.enabled or not to_locate(profile):
            return 0
        if log is not None:
            log.add("note", "Finding the suggested places on OpenStreetMap, for the map")
        placed = locate_venues(profile, (location.latitude, location.longitude), places)
        latest = store.get_profile(location.id, species) or profile
        carry_points(profile, latest)
        store.put_profile(latest)
        return placed


def main() -> None:
    from app.config import get_settings
    from app.locations import load_locations
    from app.places import places_for

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="location ids, comma-separated")
    args = parser.parse_args()
    settings = get_settings()
    store = Store(settings.cache_db)
    places = places_for(settings.geocoder_url)
    only = {x for x in args.only.split(",") if x}
    presets = {loc.id: loc for loc in load_locations(settings.locations_file)}
    for location_id, species in store.saved_profiles():
        if only and location_id not in only:
            continue
        location = presets.get(location_id) or store.get_location(location_id)
        if location is None:
            continue
        placed = locate_saved(store, location, species, places)
        print(f"{location_id} {species}: {placed} venues placed")


if __name__ == "__main__":
    main()
