"""Venue pins (decision 4, revised): points from a fake geocoder only, never Photon, and
the result view's numbered pins, cell readings and distances."""

from urllib.parse import parse_qs, urlparse

from app.places import Allowance, Places
from app.profile import Venue
from app.venue_points import locate_venues, to_locate
from app.views.build import build_result_view, cell_reading, map_view, walk
from tests.qloo_fakes import LOCATION
from tests.test_places import FakeGeocoder, feature
from tests.test_views import profile

NEAR = (LOCATION.latitude, LOCATION.longitude)


def lookup(*answers, per_minute=30):
    fake = FakeGeocoder(*answers)
    places = Places("https://geocoder.example", fake, per_visitor=Allowance(per_minute))
    places.pause = 0
    return places, fake


def test_a_venue_is_found_by_name_and_address_near_the_shelter():
    places, fake = lookup({"features": [feature("Community Hall", 40.675, -73.975)]})
    point = places.venue_point("Community Hall", "1 Example Street", NEAR)
    assert (point.latitude, point.longitude) == (40.675, -73.975)
    sent = parse_qs(urlparse(fake.urls[0]).query)
    assert sent["q"] == ["Community Hall, 1 Example Street"] and "layer" not in sent


def test_a_far_match_falls_back_to_the_address_and_else_is_dropped():
    far = {"features": [feature("Community Hall", 34.05, -118.24)]}  # another city
    near = {"features": [feature("1 Example Street", 40.676, -73.976)]}
    places, fake = lookup(far, near)
    assert places.venue_point("Community Hall", "1 Example Street", NEAR).latitude == 40.676
    assert parse_qs(urlparse(fake.urls[1]).query)["q"] == ["1 Example Street"]
    places, _ = lookup(far, far)
    assert places.venue_point("Community Hall", "1 Example Street", NEAR) is None


def test_locating_takes_the_picks_first_once_and_stops_when_throttled():
    p = profile()
    p.venues[2].chosen_reason = "a community arts centre"
    order = [v.name for v in to_locate(p)]
    assert order[0] == p.venues[2].name and "Hookah Corner" not in order  # unsuitable
    names = [v.name for v in to_locate(p)]
    answers = [{"features": [feature(n, 40.67 + k / 1000, -73.98)]} for k, n in enumerate(names)]
    places, fake = lookup(*answers, per_minute=2)
    pauses = []
    placed = locate_venues(p, NEAR, places, sleep=pauses.append)
    assert placed == 2 and len(pauses) == 2  # the third lookup was throttled
    assert sum(v.point_tried for v in p.venues) == 2
    assert len(to_locate(p)) == len(order) - 2  # the rest wait for a later save


def test_a_placed_venue_reads_its_cell_and_its_distance():
    p = profile()
    cell = p.cells[0]
    from app.qloo.geohash import bounds

    south, west, north, east = bounds(cell.geohash)
    inside = Venue(entity_id="v", name="Inside", rank=1,
                   latitude=(south + north) / 2, longitude=(west + east) / 2)  # fmt: skip
    outside = Venue(entity_id="w", name="Outside", rank=2, latitude=40.9, longitude=-73.5)
    assert cell_reading(inside, LOCATION, p).startswith(
        "OpenStreetMap places it where pet-show fans rank this part of Example Slope"
    )
    assert cell_reading(outside, LOCATION, p) == "OpenStreetMap places it outside the mapped cells."
    assert cell_reading(Venue(entity_id="u", name="Unplaced", rank=3), LOCATION, p) is None
    # Far away: no walking estimate.
    assert walk(outside, NEAR).endswith("km from the shelter in a straight line.")
    assert "min on foot" in walk(inside, NEAR)


def test_the_map_numbers_only_the_placed_venues_as_the_list_does(roster):
    p = profile()
    shown = [v for v in p.venues if v.unsuitable is None]
    shown[0].latitude, shown[0].longitude = 40.675, -73.975
    view = build_result_view(roster.get("dog-02"), LOCATION, p)
    numbered = {v.name: v.number for v in view.venues}
    pins = view.map.venues
    assert [(x.number, x.name) for x in pins] == [(numbered[shown[0].name], shown[0].name)]
    assert all(v.where is None for v in view.venues if v.name != shown[0].name)
    assert map_view(LOCATION, p).venues == []  # no venues passed, no pins


def test_a_failed_lookup_is_tried_again_later():
    # Codex, muse and Flash, PR #25: a Photon outage must not leave a venue unpinned for good.
    p = profile()
    places, _ = lookup(OSError("down"))
    assert locate_venues(p, NEAR, places, sleep=lambda s: None) == 0
    assert not any(v.point_tried for v in p.venues)


def test_a_match_without_the_venues_name_falls_back_to_its_address():
    neighbour = {"features": [feature("Corner Laundromat", 40.675, -73.975)]}
    address = {"features": [feature("", 40.6751, -73.9751)]}
    places, fake = lookup(neighbour, address)
    point = places.venue_point("Community Hall", "1 Example Street", NEAR)
    assert point.latitude == 40.6751 and len(fake.urls) == 2


def test_finishing_a_profile_keeps_its_points():
    from app.profile import finish_profile
    from tests.qloo_fakes import SEEDS, FakeQloo, standard_script

    p = profile()
    p.venues[0].latitude, p.venues[0].longitude, p.venues[0].point_tried = 40.675, -73.975, True
    p.maps_missing = 1  # unfinished
    new = finish_profile(p, LOCATION, FakeQloo(standard_script()), SEEDS)
    kept = next(v for v in new.venues if v.entity_id == p.venues[0].entity_id)
    assert (kept.latitude, kept.point_tried) == (40.675, True)
