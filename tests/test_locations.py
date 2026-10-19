import json
import re

from fastapi.testclient import TestClient

from app.config import get_settings
from app.locations import load_locations
from app.main import app

client = TestClient(app)


def test_three_presets_with_unique_ids():
    locations = load_locations(get_settings().locations_file)
    assert len(locations) == 3
    assert len({loc.id for loc in locations}) == 3


def test_start_page_offers_every_preset_with_the_first_selected():
    locations = load_locations(get_settings().locations_file)
    html = client.get("/").text
    for loc in locations:
        assert f'value="{loc.id}"' in html
        assert loc.label in html
    assert _checked_id(html) == locations[0].id


def test_location_query_parameter_preselects_a_preset():
    locations = load_locations(get_settings().locations_file)
    # Not the first preset, so the parameter is what selects it.
    other = locations[-1].id
    assert _checked_id(client.get(f"/?location={other}").text) == other
    # An unknown id falls back to the first preset rather than failing.
    assert _checked_id(client.get("/?location=nowhere").text) == locations[0].id


def test_map_gets_every_preset_point():
    html = client.get("/").text
    assert 'id="location-map"' in html
    start = html.index('id="map-points">') + len('id="map-points">')
    points = {p["id"]: p for p in json.loads(html[start : html.index("</script>", start)])}
    for loc in load_locations(get_settings().locations_file):
        assert points[loc.id]["latitude"] == loc.latitude
        assert points[loc.id]["longitude"] == loc.longitude


def test_map_scripts_are_served_and_credit_openstreetmap():
    for ui in ["classic", "warm", "story"]:
        for name in ["location-map.js", "result-map.js"]:
            js = client.get(f"/ui/{ui}/static/{name}")
            assert js.status_code == 200
            assert "OpenStreetMap" in js.text


def _checked_id(html: str) -> str:
    """The value of the location radio that is checked."""
    for match in re.finditer(r'<input type="radio" name="location" value="([^"]+)"([^>]*)>', html):
        if "checked" in match.group(2):
            return match.group(1)
    raise AssertionError("no location is checked")


def test_the_shelter_bar_names_the_chosen_area_and_stays_closed():
    # The author: the area is a setting chosen once, so it sits in a bar above the animals.
    page = client.get("/", params={"location": "astoria"}).text
    bar = page[page.index('id="shelter"') : page.index("</summary>")]
    assert "Astoria" in bar and "Queens, New York" in bar and "Change" in bar
    assert 'data-role="shelter">' in page  # closed: no "open" attribute
    assert page.index('id="shelter"') < page.index('class="animal-grid')


def test_the_api_carries_the_bar_and_the_map_caption():
    view = client.get("/api/start", params={"location": "austin"}).json()
    assert view["shelter"]["name"] == "Austin" and view["shelter"]["open"] is False
    assert view["map_note"] == next(o for o in view["locations"] if o["selected"])["map_note"]


def test_with_no_area_chosen_the_bar_asks_for_one():
    from app.animals import load_roster
    from app.views.build import build_start_view

    locations = load_locations(get_settings().locations_file)
    view = build_start_view(load_roster(get_settings().animals_file), locations, "")
    assert view.shelter.open and not view.shelter.chosen
    assert view.shelter.choose == "Choose an area"


def test_the_shelter_bar_script_is_served():
    # Flash: without it, a closed panel with no area chosen strands the visitor again.
    for ui in ["classic", "warm", "story"]:
        assert client.get(f"/ui/{ui}/static/shelter-bar.js").status_code == 200


def test_the_start_map_has_a_search_that_only_moves_it(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "geocoder_url", "https://geocoder.example")
    html = client.get("/").text
    tag = re.search(r'<input id="map-search-text"[^>]*>', html).group(0)
    # Its own form, which goes nowhere, so Enter never submits the animal picker; no name.
    assert 'form="map-search-form"' in tag and " name=" not in tag
    assert '<form id="map-search-form" method="dialog" hidden></form>' in html
    assert 'aria-controls="map-search-suggestions"' in tag
    script = client.get("/ui/warm/static/place-suggest.js").text
    assert 'new CustomEvent("namesake:fly"' in script


def test_without_place_lookups_there_is_no_map_search():
    assert 'id="map-search-text"' not in client.get("/").text
