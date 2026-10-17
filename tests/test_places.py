"""Area names for the location field and the map pick: a fake geocoder only, never Photon.

The answers below are invented, in Photon's shape (GeoJSON features).
"""

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import main
from app.custom_location import location_id
from app.locations import Location
from app.places import Allowance, Places, Throttled, areas_around, label_for
from app.store import Store
from tests.qloo_fakes import FakeQloo
from tests.test_product import (  # noqa: F401 - fixtures
    SEEDS,
    cells,
    client,
    location_script,
    profile,
)

HOME = (40.67, -73.98)


def feature(name, lat=HOME[0], lon=HOME[1], **props):
    return {
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name, **props},
    }


class FakeGeocoder:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        answer = self.answers.pop(0) if self.answers else {"features": []}
        if isinstance(answer, Exception):
            raise answer
        return answer


def places(*answers):
    fake = FakeGeocoder(*answers)
    return Places("https://geocoder.example", fetch=fake), fake


def test_an_area_is_named_with_one_wider_place():
    assert label_for({"name": "Example Slope", "type": "locality", "district": "Exampleton",
                      "city": "Example City"}) == "Example Slope, Exampleton"  # fmt: skip
    assert label_for({"name": "Example City", "type": "city", "state": "Example State",
                      "district": "Ignored"}) == "Example City, Example State"  # fmt: skip
    assert label_for({"name": "Exampleton", "type": "district", "city": "Exampleton",
                      "state": "Example State"}) == "Exampleton, Example State"  # fmt: skip
    # Names the location field would refuse are never offered.
    assert label_for({"name": "District 9", "type": "district"}) is None
    assert label_for({"type": "city"}) is None


def test_a_spot_is_named_by_the_areas_in_its_address_never_the_address():
    house = {"type": "house", "housenumber": "1", "street": "Example Street",
             "locality": "Example Slope", "district": "Exampleton", "city": "Example City",
             "state": "Example State"}  # fmt: skip
    assert areas_around(house) == [
        "Example Slope, Exampleton",
        "Exampleton, Example City",
        "Example City, Example State",
    ]
    # The nearest object's own name is never used, unless it is itself an area.
    plant = {"type": "street", "name": "Example Avenue", "city": "Example City"}
    assert areas_around(plant) == ["Example City"]
    town = {"type": "city", "name": "Example City", "state": "Example State"}
    assert areas_around(town) == ["Example City, Example State"]
    assert areas_around({"type": "house", "street": "Example Road"}) == []


def test_suggestions_ask_for_areas_only_and_are_cached():
    lookup, fake = places(
        {
            "features": [
                feature("Example Slope", type="locality", district="Exampleton"),
                feature("Example Slope", type="locality", district="Exampleton"),
                feature("Area 51", type="locality"),
            ]
        }
    )
    assert [p.label for p in lookup.search("exam")] == ["Example Slope, Exampleton"]
    asked = parse_qs(urlparse(fake.urls[0]).query)
    assert asked["q"] == ["exam"]
    assert sorted(asked["layer"]) == ["city", "district", "locality"]
    lookup.search("exam")
    assert len(fake.urls) == 1
    # Too short to be worth a lookup.
    assert lookup.search("ex") == [] and len(fake.urls) == 1


def test_suggestions_rank_near_the_map_area_given_only_to_about_11_km():
    lookup, fake = places({"features": []})
    lookup.search("example", near=(40.6712, -73.9819))
    asked = parse_qs(urlparse(fake.urls[0]).query)
    assert (asked["lat"], asked["lon"]) == (["40.7"], ["-74.0"])


def test_text_the_field_would_refuse_never_leaves_the_server():
    # Codex, muse, Flash: a pasted street address or email went to Photon as typed.
    lookup, fake = places()
    for text in ["12 Example Street", "someone@example.com", "Apt 4B, Example City"]:
        assert lookup.search(text) == []
    assert fake.urls == []


def test_an_odd_or_cut_off_answer_is_no_suggestions():
    import http.client

    odd = [[], {"features": None}, {"features": ["not a feature"]}, http.client.IncompleteRead(b"")]
    lookup, fake = places(*odd)
    for _ in odd:
        assert lookup.search("example") == []


def test_only_calls_that_reach_the_geocoder_count():
    fake = FakeGeocoder({"features": [feature("Example Slope")]})
    lookup = Places("https://geocoder.example", fake, per_visitor=Allowance(per_minute=1))
    lookup.search("example", visitor="a")
    lookup.search("example", visitor="a")  # cached: free
    lookup.search("12 Example Street", visitor="a")  # refused before any call: free
    with pytest.raises(Throttled):
        lookup.search("another example", visitor="a")
    assert len(fake.urls) == 1
    lookup.search("another example", visitor="b")


def test_everyone_together_has_an_allowance_and_a_refusal_costs_the_visitor_nothing():
    # Codex, muse, Flash: a lookup refused by the overall allowance spent the visitor's.
    fake = FakeGeocoder()
    lookup = Places(
        "https://geocoder.example", fake,
        per_visitor=Allowance(per_minute=1), overall=Allowance(per_minute=1),
    )  # fmt: skip
    lookup.search("example", visitor="a")
    with pytest.raises(Throttled):
        lookup.search("another example", visitor="b")
    lookup.overall = Allowance(per_minute=5)
    lookup.search("another example", visitor="b")  # b's one lookup is still there
    assert len(fake.urls) == 2


def test_a_lookup_refused_by_the_visitors_allowance_gives_back_everyones():
    lookup = Places(
        "https://geocoder.example", FakeGeocoder(),
        per_visitor=Allowance(per_minute=1), overall=Allowance(per_minute=2),
    )  # fmt: skip
    lookup.search("example", visitor="a")
    with pytest.raises(Throttled):
        lookup.search("another example", visitor="a")
    lookup.search("third example", visitor="b")  # everyone's second is not spent


def test_a_failed_lookup_is_not_cached():
    lookup, fake = places(OSError("down"), {"features": [feature("Example Slope")]})
    assert lookup.search("example") == []
    assert [p.label for p in lookup.search("example")] == ["Example Slope"]
    assert len(fake.urls) == 2


def test_a_picked_spot_leaves_the_server_rounded_to_about_100_m():
    house = feature(None, type="house", locality="Example Slope", district="Exampleton")
    lookup, fake = places({"features": [house]})
    found = lookup.at(40.671234, -73.981987)
    assert [p.label for p in found] == ["Example Slope, Exampleton", "Exampleton"]
    assert (found[0].latitude, found[0].longitude) == (40.671, -73.982)
    asked = parse_qs(urlparse(fake.urls[0]).query)
    assert (asked["lat"], asked["lon"]) == (["40.671"], ["-73.982"])
    # Whatever is nearest, so the area comes from its address.
    assert "layer" not in asked


def test_with_no_geocoder_nothing_is_asked():
    fake = FakeGeocoder()
    lookup = Places("", fetch=fake)
    assert lookup.search("example") == [] and lookup.at(*HOME) == []
    assert fake.urls == []


def test_each_visitor_has_a_per_minute_allowance():
    allowance = Allowance(per_minute=2)
    assert allowance.take("a") and allowance.take("a")
    assert not allowance.take("a")
    assert allowance.take("b")


# The endpoints and the pin


@pytest.fixture
def geocoder(monkeypatch):
    fake = FakeGeocoder()
    lookup = Places("https://geocoder.example", fetch=fake)
    monkeypatch.setattr(main, "places", lambda: lookup)
    return fake


def test_the_api_suggests_areas(client, geocoder):  # noqa: F811
    geocoder.answers = [{"features": [feature("Example Slope", district="Exampleton")]}]
    body = client.get("/api/places", params={"q": "example"}).json()
    assert body["places"][0]["label"] == "Example Slope, Exampleton"


def test_the_api_names_the_area_around_a_spot(client, geocoder):  # noqa: F811
    house = feature(None, type="house", locality="Example Slope", city="Example City")
    geocoder.answers = [{"features": [house]}, {"features": []}]
    found = client.get("/api/places/at", params={"lat": 40.67, "lon": -73.98}).json()
    assert [p["label"] for p in found["places"]] == ["Example Slope, Example City", "Example City"]
    empty = client.get("/api/places/at", params={"lat": 0.5, "lon": 0.5}).json()
    assert empty["places"] == [] and "No neighbourhood or city" in empty["message"]
    assert client.get("/api/places/at", params={"lat": 91, "lon": 0}).status_code == 422


def test_lookups_are_off_without_a_geocoder_and_limited_per_visitor(client, monkeypatch):  # noqa: F811
    assert client.get("/api/places", params={"q": "example"}).status_code == 404
    lookup = Places("https://geocoder.example", FakeGeocoder(), per_visitor=Allowance(1))
    monkeypatch.setattr(main, "places", lambda: lookup)
    assert client.get("/api/places", params={"q": "example"}).status_code == 200
    assert client.get("/api/places", params={"q": "example"}).status_code == 200  # cached
    assert client.get("/api/places", params={"q": "other example"}).status_code == 429


def known_area(text="Example Slope, Exampleton") -> str:
    """A checked area already in the store, so posting it costs no Qloo call."""
    Store(main.get_settings().cache_db).put_location(
        Location(
            id=location_id(text),
            label=text,
            region="Typed location",
            query=text,
            city=text,
            latitude=HOME[0],
            longitude=HOME[1],
            zoom=14,
        )  # fmt: skip
    )
    return text


def test_the_page_looks_places_up_through_the_apps_own_api():
    form = main.LocationForm()
    assert form.suggestions_url.startswith("/api/") and form.pick_url.startswith("/api/")


def option(client, loc_id):  # noqa: F811
    start = client.get("/api/start", params={"location": loc_id}).json()
    return next(o for o in start["locations"] if o["id"] == loc_id)


def test_a_picked_spot_is_this_visits_pin_and_qloo_gets_the_name(client):  # noqa: F811
    text = known_area()
    form = {"text": text, "pin_lat": "40.6712", "pin_lon": "-73.9819"}
    response = client.post("/locations", data=form, follow_redirects=False)
    assert response.status_code == 303
    loc_id = location_id(text)
    picked = option(client, loc_id)
    assert picked["pin"] == {"latitude": 40.6712, "longitude": -73.9819}
    assert "never goes to Qloo" in picked["map_note"]
    result = client.get(f"/api/results/dog-02@{loc_id}").json()
    assert result["map"]["pin"] == {"latitude": 40.6712, "longitude": -73.9819}
    # Another visitor never sees it.
    other = TestClient(main.app).get("/api/start", params={"location": loc_id}).json()
    assert next(o for o in other["locations"] if o["id"] == loc_id)["pin"] is None


def test_the_pin_is_kept_to_about_10_m_and_pages_with_it_are_never_cached(client):  # noqa: F811
    text = known_area()
    client.post("/locations", data={"text": text, "pin_lat": "40.671234", "pin_lon": "-73.98199"})
    assert option(client, location_id(text))["pin"] == {"latitude": 40.6712, "longitude": -73.982}
    page = client.get("/", params={"location": location_id(text)})
    assert page.headers["cache-control"] == "private, no-store"
    # Flash: shared files stay cacheable for a visitor with a session.
    assert "no-store" not in client.get("/ui/classic/static/style.css").headers.get(
        "cache-control", ""
    )


def test_qloo_gets_the_area_name_alone_and_candidates_keep_the_pin(client, monkeypatch):  # noqa: F811
    # Codex, Flash: Qloo's candidate buttons dropped the pin.
    monkeypatch.setattr(main, "load_seeds", lambda path: SEEDS)
    text, script = location_script(
        "needs_input",
        resolution={"issues": [{"input": "x", "kind": "ambiguous", "candidates": [
            {"id": "00000000-0000-4000-8000-000000000301", "name": "Example Heights, North",
             "type": "urn:x"}]}]},
    )  # fmt: skip
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo(script))
    page = client.post("/locations", data={"text": text, "pin_lat": "40.6", "pin_lon": "-73.9"})
    assert page.status_code == 400
    assert 'name="pin_lat" value="40.6"' in page.text and "Example Heights, North" in page.text
    # muse: Qloo's candidates live in the panel, so it opens for them too.
    assert 'data-role="shelter" open>' in page.text

    # Flash: nothing showed what Qloo received for a picked spot.
    text, script = location_script(results=cells(6))
    qloo = FakeQloo(script)
    monkeypatch.setattr(main, "replay_client", lambda settings: qloo)
    client.post("/locations", data={"text": text, "pin_lat": "40.6801", "pin_lon": "-73.9801"})
    sent = repr(qloo.calls)
    assert any(c[1].get("within") == text for c in qloo.calls)
    assert "40.68" not in sent and "-73.98" not in sent
    assert option(client, location_id(text))["pin"] == {"latitude": 40.6801, "longitude": -73.9801}


def test_a_pin_too_far_from_the_area_is_dropped_with_a_word(client):  # noqa: F811
    # muse, Flash: the drop was silent.
    text = known_area()
    response = client.post(
        "/locations", data={"text": text, "pin_lat": "40.9", "pin_lon": "-73.98"},
        follow_redirects=False,
    )  # fmt: skip
    assert response.headers["location"].endswith("&pin=far")
    start = client.get("/api/start", params={"location": location_id(text), "pin": "far"}).json()
    picked = next(o for o in start["locations"] if o["id"] == location_id(text))
    assert picked["pin"] is None and "more than 15 km" in picked["map_note"]
    # Codex: the note is in the panel, so it opens.
    page = client.get("/", params={"location": location_id(text), "pin": "far"}).text
    assert 'data-role="shelter" open>' in page
    # Flash: a far pick after a near one replaces it, rather than seeming to work.
    client.post("/locations", data={"text": text, "pin_lat": "40.67", "pin_lon": "-73.98"})
    assert option(client, location_id(text))["pin"] is not None
    client.post("/locations", data={"text": text, "pin_lat": "40.9", "pin_lon": "-73.98"})
    assert option(client, location_id(text))["pin"] is None


def test_a_pin_far_from_the_area_or_not_a_number_is_dropped(client):  # noqa: F811
    text = known_area()
    loc_id = location_id(text)
    for lat, lon in [("51.5", "-0.12"), ("nan", "nan"), ("", ""), ("x", "1")]:
        client.post("/locations", data={"text": text, "pin_lat": lat, "pin_lon": lon})
        assert option(client, loc_id)["pin"] is None


def test_a_failed_area_check_leaves_no_area_chosen(client, monkeypatch):  # noqa: F811
    # The author: whatever was chosen on the map, Park Slope was still checked, since a
    # failed check came back with the first preset selected and the message out of view.
    monkeypatch.setattr(main, "replay_client", lambda settings: FakeQloo({}))
    page = client.post(
        "/locations", data={"text": "Example Gardens", "pin_lat": "40.6", "pin_lon": "-73.9"}
    )
    assert page.status_code == 503
    assert 'id="location-alert" role="alert"' in page.text
    # The panel holding the alert and the required choice opens by itself.
    assert 'data-role="shelter" open>' in page.text and "not chosen yet" in page.text
    assert 'class="shelter unchosen"' in page.text
    assert (
        " checked>" not in page.text and 'name="location" value="park-slope" required' in page.text
    )
    assert 'name="pin_lat" value="40.6"' in page.text
    # Codex: "Add your own animal" skipped the check and fell back to the first preset.
    assert "formnovalidate" not in page.text
