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
    assert _checked_id(client.get("/?location=austin").text) == "austin"
    # An unknown id falls back to the first preset rather than failing.
    assert _checked_id(client.get("/?location=nowhere").text) == "park-slope"


def test_map_gets_every_preset_point():
    html = client.get("/").text
    assert 'id="location-map"' in html
    start = html.index('id="map-points">') + len('id="map-points">')
    points = json.loads(html[start : html.index("</script>", start)])
    for loc in load_locations(get_settings().locations_file):
        assert points[loc.id]["latitude"] == loc.latitude
        assert points[loc.id]["longitude"] == loc.longitude


def test_map_script_is_served_and_credits_openstreetmap():
    js = client.get("/static/location-map.js")
    assert js.status_code == 200
    assert "OpenStreetMap" in js.text


def _checked_id(html: str) -> str:
    """The value of the location radio that is checked."""
    for match in re.finditer(r'<input type="radio" name="location" value="([^"]+)"([^>]*)>', html):
        if "checked" in match.group(2):
            return match.group(1)
    raise AssertionError("no location is checked")
