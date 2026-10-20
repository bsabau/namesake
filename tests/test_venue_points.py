"""Venue pins (decision 4, revised): points from a fake geocoder only, never Photon, and
the result view's numbered pins, cell readings and distances."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.places import Allowance, Places
from app.profile import Venue
from app.venue_points import locate_venues, to_locate
from app.views.build import (
    VENUES_SHOWN,
    build_result_view,
    cell_of,
    cell_reading,
    map_view,
    venue_order,
    venues_for_animal,
    walk,
)
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


def test_locating_follows_the_page_once_and_stops_when_throttled():
    p = profile()
    order = [v.name for v in to_locate(p)]
    assert order == [v.name for v in venue_order(p)][: len(order)]
    assert "Hookah Corner" not in order  # unsuitable
    answers = [{"features": [feature(n, 40.67 + k / 1000, -73.98)]} for k, n in enumerate(order)]
    places, fake = lookup(*answers, per_minute=2)
    placed = locate_venues(p, NEAR, places)
    assert placed == 2  # the third lookup was throttled
    assert sum(v.point_tried for v in p.venues) == 2
    assert len(to_locate(p)) == len(order) - 2  # the rest wait for a later save


def test_every_venue_a_page_shows_is_looked_up_and_no_other():
    p = profile()
    p.venues = [
        Venue(entity_id=f"v{k}", name=name, rank=k)
        for k, name in enumerate(
            ["Hall", "Kids Gym", "Toddler Corner", "Gallery", "Bar", "Club", "Loft", "Barn"],
            start=1,
        )
    ]
    every = venue_order(p)
    no_children = SimpleNamespace(checks=SimpleNamespace(good_with_children="no"))
    shown = every[:VENUES_SHOWN] + venues_for_animal(no_children, every)[0][:VENUES_SHOWN]
    names = [v.name for v in to_locate(p)]
    assert set(names) == {v.name for v in shown}
    assert "Loft" in names and "Barn" not in names  # Loft is 5th on a page without the two
    for venue in p.venues:
        venue.point_tried = venue.name in names
    assert to_locate(p) == []  # a second pass looks up nothing a page does not show


def test_an_agent_profile_is_looked_up_in_its_own_page_order():
    p = profile()
    p.made_by = "agent"
    # Place 7 stands out for fans of pet-themed titles, but the page lists the AI's picks by rank.
    p.venues = [
        Venue(entity_id=f"v{k}", name=f"Place {k}", rank=k, chosen_reason="a place to ask",
              compared=True, baseline_rank=None if k == 7 else 1)
        for k in range(1, 8)
    ]  # fmt: skip
    assert [v.name for v in to_locate(p)] == [f"Place {k}" for k in range(1, 6)]


def test_a_placed_venue_reads_its_cell_and_its_distance():
    p = profile()
    cell = p.cells[0]
    from app.qloo.geohash import bounds

    south, west, north, east = bounds(cell.geohash)
    inside = Venue(entity_id="v", name="Inside", rank=1,
                   latitude=(south + north) / 2, longitude=(west + east) / 2)  # fmt: skip
    outside = Venue(entity_id="w", name="Outside", rank=2, latitude=40.9, longitude=-73.5)
    assert cell_reading(inside, LOCATION, p).startswith(
        "On the map, which compares areas rather than places, OpenStreetMap places it where "
        "fans of pet-themed titles rank this part of Example Slope"
    )
    assert cell_reading(outside, LOCATION, p) == "OpenStreetMap places it beyond the map's view."
    near_out = Venue(entity_id="n", name="Near", rank=4, latitude=NEAR[0] + 0.01, longitude=NEAR[1])
    if cell_of(near_out, p) is None:
        assert cell_reading(near_out, LOCATION, p) == (
            "OpenStreetMap places it outside the mapped cells."
        )
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
    places, fake = lookup(OSError("down"))
    assert locate_venues(p, NEAR, places) == 0
    assert not any(v.point_tried for v in p.venues)
    assert len(fake.urls) == 1  # Photon is down: stop asking, count nothing against venues


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


def test_a_far_pin_is_not_drawn_and_the_key_counts_only_drawn_ones():
    p = profile()
    shown = [v for v in p.venues if v.unsuitable is None]
    shown[0].latitude, shown[0].longitude = 40.9, -73.5  # about 40 km away
    view = map_view(LOCATION, p, None, shown)
    assert view.venues == [] and "Numbers:" not in (view.note or "")
    shown[1].latitude, shown[1].longitude = NEAR[0] + 0.001, NEAR[1]
    view = map_view(LOCATION, p, None, shown)
    assert (
        [x.number for x in view.venues] == [2]
        and "Numbers: the places to ask" in view.note
        and "need not sit in a warm cell" in view.note
    )


def test_points_placed_meanwhile_survive_a_finished_profile_and_the_reverse():
    from app.profile import carry_points

    old, new = profile(), profile()
    old.venues[0].latitude, old.venues[0].point_tried = 40.675, True
    carry_points(old, new)
    assert new.venues[0].latitude == 40.675 and new.venues[0].point_tried
    # A venue already placed in the newer copy keeps its own point.
    other = profile()
    other.venues[0].latitude, other.venues[0].point_tried = 40.1, True
    carry_points(other, new)
    assert new.venues[0].latitude == 40.675


def test_an_odd_answer_is_no_match_and_does_not_hold_up_the_rest():
    # Flash, PR #25: a venue whose answer is unusable must not block the others for good.
    p = profile()
    first, second = to_locate(p)[:2]
    odd = {"features": [{"properties": {"name": first.name}}]}  # no geometry
    places, _ = lookup(
        odd,  # the first venue's name and address
        odd,  # and its address alone
        {"features": [feature(second.name, NEAR[0] + 0.001, NEAR[1])]},
    )
    assert locate_venues(p, NEAR, places) == 1
    assert first.point_tried and first.latitude is None and second.latitude is not None


def test_a_name_match_needs_the_distinctive_words():
    from app.places import same_name

    assert same_name("Brooklyn Arts Exchange", "Brooklyn Arts Exchange (BAX)")
    assert not same_name("Bell House", "Bell Rock Tavern")
    assert not same_name("Littlefield Hall", "Littlefield Deli")
    assert same_name("Ola", "Ola Bar") and not same_name("Ola", "Bolanos")


def test_a_point_that_is_not_a_number_is_no_point():
    nan = {"features": [{"geometry": {"coordinates": ["nan", "nan"]},
                         "properties": {"name": "Community Hall"}}]}  # fmt: skip
    places, _ = lookup(nan, nan)
    assert places.venue_point("Community Hall", "1 Example Street", NEAR) is None
