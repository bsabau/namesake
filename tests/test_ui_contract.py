"""The contract every UI folder must meet: each screen renders the required elements.

A new UI under `app/ui/` is picked up automatically and must pass this test.
"""

import re

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

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
    "flyer": ["flyer", "name", "flyer-contact", "flyer-checklist", "photo-credit", "qloo-credit"],
}


@pytest.fixture
def client(monkeypatch):
    # Pages read the profile through this function; give them a synthetic one.
    def fake_profile(location, species):
        from tests.qloo_fakes import LOCATION

        return build_profile(FakeQloo(standard_script()), LOCATION.model_copy(), SEEDS)

    monkeypatch.setattr(main, "location_profile", fake_profile)
    return TestClient(main.app)


def test_every_skin_is_found():
    assert {"classic", "warm", "story"} <= set(main.UIS)


def test_the_default_ui_is_story():
    # The declared default, not the effective one: a UI=classic override is allowed.
    assert type(get_settings()).model_fields["ui"].default == "story"
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
def test_flyer_meets_the_contract(client, ui):
    response = client.get("/flyer", params={"animal": "dog-02", "location": "park-slope", "ui": ui})
    assert response.status_code == 200
    for role in REQUIRED["flyer"]:
        assert f'data-role="{role}"' in response.text, f"{ui} flyer: missing {role}"


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
    assert "The run stopped on an error in Namesake's code" in lines[-2]
    assert "RuntimeError" not in lines[-2] and "RuntimeError" not in lines[-1]
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


@pytest.mark.parametrize("ui", ["warm", "story"])
def test_the_fonts_are_self_hosted_and_cacheable(client, ui):
    fonts = main.UI_ROOT / ui / "static" / "fonts"
    files = sorted(fonts.glob("*.woff2"))
    assert files and (fonts / "OFL.txt").exists(), "the font ships with its licence"
    if ui == "story":
        assert (fonts / "OFL-fraunces.txt").exists(), "Fraunces ships with its licence"
    for path in files:
        response = client.get(f"/ui/{ui}/static/fonts/{path.name}")
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


def test_story_maps_take_their_tiles_from_the_view_model(client, monkeypatch):
    # The basemap is the view model's (CARTO with the MAP_TILES_KEY setting, else
    # OpenStreetMap); the scripts never name a tile server, let alone a key.
    for name in ["result-map.js", "location-map.js"]:
        script = (main.UI_ROOT / "story" / "static" / name).read_text(encoding="utf-8")
        assert "addBasemap(map, container" in script
        assert (
            "key=" not in script and "cartocdn" not in script and "tile.openstreetmap" not in script
        )
    monkeypatch.setattr(get_settings(), "map_tiles_key", SecretStr("test-key"))
    start = client.get("/", params={"ui": "story"}).text
    assert 'id="map-tiles"' in start and "key=test-key" in start
    result = client.get(
        "/result", params={"animal": "dog-02", "location": "park-slope", "ui": "story"}
    ).text
    assert "dark_all" in result and "key=test-key" in result


def test_the_story_result_tells_the_story_in_order(client, monkeypatch):
    # The structure the skin was built to (docs/img/story-structure.png, decision 24),
    # with the outcome first and the how after the places (decision 33).
    fake_profile = main.location_profile

    def with_reasons(location, species):
        # Places Namesake's AI gave a reason for, so the card shows its reading.
        profile = fake_profile(location, species)
        for v in profile.venues:
            v.chosen_reason = "a community place"
        return profile

    monkeypatch.setattr(main, "location_profile", with_reasons)
    page = client.get(
        "/result", params={"animal": "dog-02", "location": "park-slope", "ui": "story"}
    ).text
    marks = [
        "tell her story.",
        "Choose a name",
        # Hidden with the names under the generic version, whose names are not Qloo's.
        'class="local-touch local-only"',
        "Her introduction",
        'data-role="approve"',
        "Want the wording or the names changed?",
        "Not yet known, so not mentioned",
        "Help her story travel",
        'data-role="map"',
        "Places to ask",
        'data-role="venues-note"',
        "Other ways to help",
        'id="how-heading"',
        'data-role="qloo-part"',
        'data-role="qloo-returned"',
        'data-role="our-reading"',
        'class="trial"',
        'data-role="qloo-credit"',
    ]
    positions = [page.index(mark) for mark in marks]
    assert positions == sorted(positions), marks
    assert "What we know" in page and "Still to learn: children" in page
    # One line per version, each naming Qloo once; the generic one claims no names.
    assert "Qloo From Qloo" not in page and page.count("From Qloo taste data for") == 2
    generic = page.split('class="local-touch version-generic">')[1].split("</p>")[0]
    assert "names" not in generic and "places to ask" in generic
    # Each place leads with Qloo's rank, before the AI's reading of it; the fold keeps
    # Qloo's answer, labelled (decision 33, revised 23 October).
    cards = [c.split("</li>")[0] for c in page.split('<li class="venue">')[1:]]
    read = [c for c in cards if "<span>Namesake's AI:</span>" in c]
    assert read, "a place the AI gave a reason for"
    for card in cards:
        rank = card.index('data-role="venue-rank"')
        assert "<span>Qloo:</span> <strong>" in card[rank:] and rank < card.index("venue-why")
    for card in read:
        rank = card.index('data-role="venue-rank"')
        assert rank < card.index("<span>Namesake's AI:</span>") < card.index('class="venue-why"')
    card = cards[0]
    fold = card.split('<details class="venue-why">')[1].split("</details>")[0]
    assert '<p class="evidence"><span>Qloo:</span>' in fold and "venue-rank" not in fold


@pytest.mark.parametrize("ui", [u for u in main.UIS if u != "story"])
def test_the_other_skins_keep_qloos_part_first(client, ui):
    # Decision 33 reordered the story skin only: warm and classic open with Qloo's part.
    page = client.get(
        "/result", params={"animal": "dog-02", "location": "park-slope", "ui": ui}
    ).text
    assert 'class="local-touch' not in page and 'class="trial"' not in page
    assert page.index('data-role="qloo-part"') < page.index('data-role="listing"')


@pytest.mark.parametrize("ui", main.UIS)
def test_a_name_options_title_always_carries_the_qloo_label(ui):
    # The title under a name is Qloo's answer: wherever a skin prints it, the line carries
    # the Qloo label on an evidence line, never bare under Namesake's name.
    template = (main.UI_ROOT / ui / "templates" / "result.html").read_text(encoding="utf-8")
    lines = [line for line in template.splitlines() if "option.title" in line]
    assert lines, f"{ui} result: no name option title"
    for line in lines:
        assert "evidence" in line and "<span>Qloo" in line, f"{ui}: {line.strip()}"


def test_story_maps_fall_back_when_the_keyed_basemap_fails():
    # A refused key, a quota or an outage must not leave the map blank: after a few tile
    # errors the scripts switch to the fallback the view model names (OpenStreetMap).
    for name in ["result-map.js", "location-map.js"]:
        script = (main.UI_ROOT / "story" / "static" / name).read_text(encoding="utf-8")
        assert (
            "tileerror" in script and "fallback_url" in script and "fallback_attribution" in script
        )
        assert "tileload" in script


# The map script, run in node with a stub Leaflet, so the fallback's behaviour is tested,
# not only its wording. The page's IIFE finds no map container and returns at once.
BASEMAP_HARNESS = """
const made = [];
globalThis.L = { tileLayer(url, options) {
  const layer = { url, options, handlers: {}, on(e, cb) { this.handlers[e] = cb; return this; },
    addTo() { made.push(this); return this; }, remove() {} };
  return layer;
} };
const schemeListeners = [];
globalThis.matchMedia = () => ({
  matches: false, addEventListener: (_, cb) => schemeListeners.push(cb),
});
globalThis.document = { getElementById: () => null };
const classes = new Set();
const container = { classList: {
  toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), add: (c) => classes.add(c),
} };
%s
const tiles = {
  url: "https://keyed.example/{z}", dark_url: "https://keyed-dark.example/{z}",
  attribution: "keyed", subdomains: "abcd", max_zoom: 20,
  fallback_url: "https://plain.example/{z}", fallback_attribution: "plain", fallback_max_zoom: 19,
};
addBasemap({}, container, tiles);
const out = [];
const current = () => made[made.length - 1];
const fire = (e) => current().handlers[e] && current().handlers[e]();
// Two errors, a loaded tile, two more errors: still the keyed layer.
fire("tileerror"); fire("tileerror"); fire("tileload"); fire("tileerror"); fire("tileerror");
out.push(current().url);
// A scheme change starts a fresh count (the loaded tile first clears the two pending).
fire("tileload"); fire("tileerror"); fire("tileerror");
schemeListeners.forEach((cb) => cb());
fire("tileerror"); fire("tileerror");
out.push(current().url);
// Three in a row: the fallback, with its own attribution, and the plain-tiles mark.
fire("tileerror");
out.push(current().url, current().options.attribution);
out.push(String(classes.has("tiles-plain")), String(made.length));
console.log(JSON.stringify(out));
"""


@pytest.mark.parametrize("name", ["result-map.js", "location-map.js"])
def test_the_fallback_waits_for_three_errors_in_a_row(name):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (main.UI_ROOT / "story" / "static" / name).read_text(encoding="utf-8")
    result = subprocess.run(
        [node, "-e", BASEMAP_HARNESS % script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out[:2] == ["https://keyed.example/{z}", "https://keyed.example/{z}"]
    # Three layers in all: the first, the one after the scheme change, the fallback.
    assert out[2:] == ["https://plain.example/{z}", "plain", "true", "3"]


def test_the_story_working_page_marks_each_step_by_who_did_it(client):
    # The timeline's marks come from each step's own actor: the view model's StepView.actor
    # for rendered steps, the event's actor for streamed ones; never a guess in the script.
    page = client.post(
        "/runs", data={"animal": "dog-02", "location": "park-slope", "ui": "story"}
    ).text
    assert 'data-actor-labels="' in page and "&#34;classifier&#34;" in page
    assert "Writing her story…" in page
    for label in ["Qloo", "Namesake&#39;s AI", "Classifier (TypeSafe&#39;s Jev)", "Code"]:
        assert label in page
    # Whatever the run logged first (a saved result, a fresh start), each rendered step
    # carries its actor as a class and in words.
    steps = re.findall(
        r'class="step step-[a-z]+ actor-([a-z]+)"><span class="step-actor">([^<]+)</span>', page
    )
    assert steps and all(label for _, label in steps)
    assert 'class="steps timeline" data-role="steps"' in page
    # Streamed steps take their actor from the event, never from the kind; the label from
    # the view model's list; a step without an actor is code's.
    script = (main.UI_ROOT / "story" / "static" / "working.js").read_text(encoding="utf-8")
    assert "root.dataset.actorLabels" in script and 'step.actor || "code"' in script
    assert "actors[step.kind]" not in script


def test_every_actor_renders_in_words_and_colour_on_the_story_working_page(monkeypatch):
    # A Qloo call, an AI decision, the classifier's sorting and a code note, each with its
    # actor in text and in its class, on the page and on the stream.
    import asyncio

    import app.runs as runs

    async def scripted(*args, **kwargs):
        log = kwargs["log"]
        log.add("qloo", "Asking Qloo which TV shows people around Example tend to like")
        log.add("decision", "The litter's names will all come from Example Show")
        log.add("note", "20 TV shows: the classifier found 3 about pets", actor="classifier")
        log.add("note", "Qloo returned 15 places; 4 stand out against the baseline")
        while not log._listeners:
            await asyncio.sleep(0.01)

    monkeypatch.setattr(runs, "run_pipeline", scripted)
    with TestClient(main.app) as client:
        location = client.post(
            "/runs",
            data={"animal": "dog-02", "location": "park-slope", "ui": "story"},
            follow_redirects=False,
        ).headers["location"]
        run_id = location.rsplit("?", 1)[0].rsplit("/", 1)[-1]
        with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
            lines = [line for line in stream.iter_lines() if line.startswith("data:")]
        page = client.get(f"/runs/{run_id}", params={"ui": "story"}).text
    import json

    events = [json.loads(line[5:]) for line in lines[:-1]]
    assert [e["actor"] for e in events] == ["qloo", "ai", "classifier", "code"]
    assert all(set(e) == {"kind", "text", "actor"} for e in events)
    assert 'class="step step-qloo actor-qloo"><span class="step-actor">Qloo</span>' in page
    assert (
        'class="step step-decision actor-ai"><span class="step-actor">Namesake&#39;s AI</span>'
        in page
    )
    assert (
        'class="step step-note actor-classifier"><span class="step-actor">'
        "Classifier (TypeSafe&#39;s Jev)</span>" in page
    )
    assert (
        'class="step step-note actor-code"><span class="step-actor">Code</span> '
        "Qloo returned 15 places" in page
    )


def test_the_story_start_page_reads_as_the_result_does(client, monkeypatch):
    # Finished stories first, then 01 the shelter area and 02 the animals as taped photos.
    import app.store as store_module

    page = client.get("/", params={"ui": "story"}).text
    assert page.index('class="headline"') < page.index('data-role="shelter"')
    assert page.index('class="step-no" aria-hidden="true">01') < page.index('data-role="shelter"')
    assert page.index('data-role="shelter"') < page.index('class="step-no" aria-hidden="true">02')
    assert page.index(">02") < page.index('class="animal-grid taped"')
    # The radio markup the location tests read is unchanged.
    assert re.search(
        r'<input type="radio" name="location" value="park-slope" required\s+checked>', page
    )
    # With a saved example, the band of finished stories comes before 01.
    monkeypatch.setattr(store_module.Store, "get_listing", lambda self, a, loc: object())
    page = client.get("/", params={"ui": "story"}).text
    assert 'class="examples band" data-role="examples"' in page
    assert page.index("Read a finished story") < page.index('aria-hidden="true">01')
