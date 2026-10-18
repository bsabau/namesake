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
    return Places("https://geocoder.example", fake, per_visitor=Allowance(per_minute)), fake


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
    answers = [{"features": [feature("x", 40.67 + n / 1000, -73.98)]} for n in range(10)]
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
    assert cell_reading(inside, p).startswith("On the map, ")
    assert cell_reading(outside, p) == "Outside the mapped cells."
    assert cell_reading(Venue(entity_id="u", name="Unplaced", rank=3), p) is None
    assert walk(outside, NEAR).endswith("min on foot in a straight line.")


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
