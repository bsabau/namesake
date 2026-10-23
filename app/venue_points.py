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

from app.agent.steps import StepLog
from app.locations import Location
from app.places import LookupFailed, Places, Throttled
from app.profile import LocationProfile, Venue, carry_points
from app.store import Store
from app.views.build import VENUES_SHOWN, for_children, venue_order


def to_locate(profile: LocationProfile, shelter: tuple[float, float] | None = None) -> list[Venue]:
    """The venues a page may show that are not looked up yet, in the page's order: its
    first VENUES_SHOWN, and the first VENUES_SHOWN of an animal recorded as not good with
    children, whose page skips venues that mention children. No other venue is looked up.
    Given the shelter's centre, a pinned venue too far from it is out of the page's order
    (decision 40), so the next one is looked up in its place."""
    every = venue_order(profile, shelter)
    for_any = [v for v in every if not for_children(v.name, v.description)]
    window = {v.entity_id for v in every[:VENUES_SHOWN] + for_any[:VENUES_SHOWN]}
    return [v for v in every if v.entity_id in window and not v.point_tried]


def locate_venues(
    profile: LocationProfile,
    near: tuple[float, float],
    places: Places,
) -> int:
    """Look up the venues not yet tried; returns how many were placed. Stops quietly when
    Photon's allowance is spent: the rest are tried on a later save."""
    placed = 0
    # A venue pinned too far drops out of the page's order and lets the next one in, so
    # look again until every venue the page may show has been tried (decision 40).
    while todo := to_locate(profile, near):
        for venue in todo:
            try:
                point = places.venue_point(venue.name, venue.address, near)
            except (Throttled, LookupFailed):
                # The allowance is spent, or Photon is down: nothing is counted against the
                # venues, and a later save tries the rest. (An odd answer is no match.)
                return placed
            venue.point_tried = True
            if point is not None:
                venue.latitude, venue.longitude = point.latitude, point.longitude
                placed += 1
    return placed


# One writer of a profile's points at a time: the placer, and a run finishing the profile
# (save_keeping_points), which merge onto the profile as saved under the same lock.
_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(location_id: str, species: str) -> threading.Lock:
    with _locks_guard:  # the first two writers of a profile get the same lock
        return _locks.setdefault((location_id, species), threading.Lock())


def save_keeping_points(store: Store, profile: LocationProfile, location_id: str) -> None:
    """Save a finished profile, carrying the points the placer saved meanwhile."""
    with _lock(location_id, profile.species):
        latest = store.get_profile(location_id, profile.species)
        if latest is not None:
            carry_points(latest, profile)
        store.put_profile(profile)


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
    with _lock(location.id, species):
        profile = store.get_profile(location.id, species)
        centre = (location.latitude, location.longitude)
        if profile is None or not places.enabled or not to_locate(profile, centre):
            return 0
        if log is not None:
            log.add("note", "Finding the suggested places on OpenStreetMap, for the map")
        placed = locate_venues(profile, centre, places)
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
