"""The contract every UI folder must meet: each screen renders the required elements.

A new UI under `app/ui/` is picked up automatically and must pass this test.
"""

import re

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import get_settings
from app.profile import build_profile
from tests.qloo_fakes import SEEDS, FakeQloo, standard_script

REQUIRED = {
    "start": ["shelter", "map", "photo-credit", "qloo-credit"],
    "working": ["working", "steps", "status", "photo-credit", "qloo-credit"],
    "result": [
        "name",
        "version-toggle",
        "version-generic",
        "version-local",
        "approve",
        "refine",
        "qloo-part",
        "qloo-returned",
        "our-reading",
        "map",
        "photo-credit",
        "qloo-credit",
    ],
    "add_animal": ["add-animal", "photo-credit", "qloo-credit"],
}


@pytest.fixture
def client(monkeypatch):
    # Pages read the profile through this function; give them a synthetic one.
    def fake_profile(location, species):
        from tests.qloo_fakes import LOCATION

        return build_profile(FakeQloo(standard_script()), LOCATION.model_copy(), SEEDS)

    monkeypatch.setattr(main, "location_profile", fake_profile)
    return TestClient(main.app)


def test_both_skins_are_found():
    assert {"classic", "warm"} <= set(main.UIS)


def test_the_default_ui_is_warm():
    # The declared default, not the effective one: a UI=classic override is allowed.
    assert type(get_settings()).model_fields["ui"].default == "warm"
    assert main.pick_ui(None) == get_settings().ui


def test_every_ui_has_every_screen():
    # A skin copied from classic must keep every template and script, or a route 500s.
    def names(ui, suffix):
        found = (main.UI_ROOT / ui).rglob(f"*{suffix}")
        return {p.name for p in found if not p.name.startswith("_")}

    for ui in main.UIS:
        assert names(ui, ".html") == names("classic", ".html"), f"{ui} lacks a template"
        assert names(ui, ".js") == names("classic", ".js"), f"{ui} lacks a script"


@pytest.mark.parametrize("ui", main.UIS)
def test_start_screen_meets_the_contract(client, ui):
    html = client.get("/", params={"ui": ui}).text
    for role in REQUIRED["start"]:
        assert f'data-role="{role}"' in html, f"{ui} start: missing {role}"


@pytest.mark.parametrize("ui", main.UIS)
def test_result_screen_meets_the_contract(client, ui):
    response = client.get(
        "/result", params={"animal": "dog-02", "location": "park-slope", "ui": ui}
    )
    assert response.status_code == 200
    for role in REQUIRED["result"]:
        assert f'data-role="{role}"' in response.text, f"{ui} result: missing {role}"


@pytest.mark.parametrize("ui", main.UIS)
def test_working_screen_meets_the_contract(client, ui):
    response = client.post("/runs", data={"animal": "dog-02", "location": "park-slope", "ui": ui})
    assert response.status_code == 200
    for role in REQUIRED["working"]:
        assert f'data-role="{role}"' in response.text, f"{ui} working: missing {role}"


def test_the_working_screen_shows_a_sign_of_life_while_running(client, monkeypatch):
    # Runs end at once without a model, so the page is shown as if still running.
    built = main.working_view
    monkeypatch.setattr(
        main, "working_view", lambda *a, **k: built(*a, **k).model_copy(update={"finished": False})
    )
    response = client.post("/runs", data={"animal": "dog-02", "location": "park-slope"})
    words = main.WorkingView.model_fields["busy_words"].default
    assert 'data-role="busy"' in response.text and words[0] in response.text


@pytest.mark.parametrize("ui", main.UIS)
def test_ui_folders_never_reach_for_data(ui):
    # A UI renders view models only: no fetches outside the app's own /api/.
    for path in (main.UI_ROOT / ui).rglob("*"):
        if path.suffix in {".html", ".js", ".css"}:
            text = path.read_text(encoding="utf-8")
            for call in ["qloo exec", "qloo mcp", "/v2/", "hackathon.api"]:
                assert call not in text, f"{path.name} reaches for Qloo: {call}"
            # Place lookups go through /api/places, never to the geocoder itself.
            assert "photon" not in text.lower(), f"{path.name} reaches for the geocoder"
            # Fonts are served from the UI's own folder: no visitor is sent to a font service.
            for host in ["fonts.googleapis.com", "fonts.gstatic.com"]:
                assert host not in text, f"{path.name} loads a font from {host}"
            # Every fetch goes to a URL the page was given (a data-*-url from the view
            # model, under /api/), never to a URL written into the script.
            for call in re.findall(r"fetch\(([^)]*)\)", text):
                assert "dataset" in call or "Url" in call or "/api/" in call, call
                assert not re.search(r"[`'\"]https?:", call), f"{path.name} fetches {call}"


def test_unknown_ui_is_a_404(client):
    assert client.get("/", params={"ui": "no-such-ui"}).status_code == 404


def test_a_failed_run_reports_its_error_and_does_not_send_to_a_result(monkeypatch):
    # Regression (Codex, milestone 3): the stream ended before the error and said "done".
    import app.runs as runs

    async def broken(*args, **kwargs):
        import asyncio

        log = kwargs["log"]
        log.add("qloo", "Looking something up")
        # Fail only once the page is listening, which is when the old order lost the error.
        while not log._listeners:
            await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    monkeypatch.setattr(runs, "run_pipeline", broken)
    # One client for both requests, so the run's task and the stream share an event
    # loop, as they do under a real server.
    with TestClient(main.app) as client:
        location = client.post(
            "/runs", data={"animal": "dog-02", "location": "park-slope"}, follow_redirects=False
        ).headers["location"]
        run_id = location.rsplit("/", 1)[-1]
        with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
            lines = [line for line in stream.iter_lines() if line.startswith("data:")]
    assert "The run stopped: RuntimeError" in lines[-2]
    assert '"failed": true' in lines[-1]


@pytest.mark.parametrize("ui", main.UIS)
def test_add_animal_screen_meets_the_contract(client, ui):
    html = client.get("/animals/new", params={"location": "park-slope", "ui": ui}).text
    for role in REQUIRED["add_animal"]:
        assert f'data-role="{role}"' in html, f"{ui} add animal: missing {role}"


@pytest.mark.parametrize("ui", main.UIS)
def test_ui_files_are_linked_with_their_version(client, ui):
    # A script cached from before a deploy kept running against the new page.
    page = client.get("/", params={"ui": ui}).text
    version = main.static_version(ui)
    assert f"location-map.js?v={version}" in page and f"style.css?v={version}" in page


def test_the_default_ui_is_served_at_the_root(client):
    version = main.static_version(get_settings().ui)
    assert f"/ui/{get_settings().ui}/static/style.css?v={version}" in client.get("/").text


def test_the_warm_font_is_self_hosted_and_cacheable(client):
    fonts = main.UI_ROOT / "warm" / "static" / "fonts"
    files = sorted(fonts.glob("*.woff2"))
    assert files and (fonts / "OFL.txt").exists(), "the font ships with its licence"
    for path in files:
        response = client.get(f"/ui/warm/static/fonts/{path.name}")
        assert response.status_code == 200
        # Registered in app/main.py: a slim Linux image has no mime.types file for .woff2.
        assert response.headers["content-type"] == "font/woff2"
        # Shared files are cacheable: a validator is sent and no session rule forbids it.
        assert "etag" in response.headers or "last-modified" in response.headers
        assert "no-store" not in response.headers.get("cache-control", "")
        assert len(response.content) < 150_000, f"{path.name} is not a subsetted woff2"
    css = (fonts.parent / "style.css").read_text(encoding="utf-8")
    assert "@font-face" in css and "font-display: swap" in css


@pytest.mark.parametrize("ui", main.UIS)
def test_provenance_lines_are_marked_in_every_ui(ui):
    # What Qloo returned and how Namesake read it stay two marked lines, never one.
    template = (main.UI_ROOT / ui / "templates" / "result.html").read_text(encoding="utf-8")
    for marker in ['class="evidence"', 'class="reading"', "from-qloo"]:
        assert marker in template, f"{ui} result: no {marker}"


@pytest.mark.parametrize("ui", main.UIS)
def test_qloo_text_on_a_venue_sits_under_qloo_label(ui):
    # Qloo's description of a venue is Qloo's words: it goes on the card's Qloo line.
    template = (main.UI_ROOT / ui / "templates" / "result.html").read_text(encoding="utf-8")
    lines = [line for line in template.splitlines() if "venue.description" in line]
    assert lines, f"{ui} result: no venue description"
    for line in lines:
        assert '<p class="evidence"><span>Qloo:</span>' in line, f"{ui}: {line.strip()}"


@pytest.mark.parametrize("ui", main.UIS)
def test_the_map_colours_cells_as_the_caption_counts_them(ui):
    # The caption counts lift above zero as warm (app/views/build.py map_view); a tie is
    # cool, and a compared cell never draws paler than a grey one.
    script = (main.UI_ROOT / ui / "static" / "result-map.js").read_text(encoding="utf-8")
    assert "cell.lift > 0 ? warm : cool" in script
    assert "cell.lift === null ? 0.25 : 0.3 + 0.5 * Math.min(1, Math.abs(cell.lift))" in script


@pytest.mark.parametrize("ui", main.UIS)
def test_the_venues_note_is_labelled_as_namesakes_reading(client, ui):
    # The kinds of place are Namesake's choice, so the note carries its label (decision 23).
    page = client.get(
        "/result", params={"animal": "dog-02", "location": "park-slope", "ui": ui}
    ).text
    assert 'data-role="venues-note"><span>Namesake:</span>' in page
