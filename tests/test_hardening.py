"""The live demo's defences after the final audits (19 October): request sizes, posts from
other sites, security headers, a bounded run list, memory for photos, a styled 404, a form
that keeps what was typed, and caps on the AI's own Qloo calls."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, runs
from app.agent.profile_agent import (
    MAX_LOOKUPS,
    MAX_VENUE_SEARCHES,
    ProfileDeps,
    find_venues,
    look_up_title,
)
from app.agent.steps import StepLog
from app.profile import Entity, venue_input
from tests.qloo_fakes import DOG_SHOW, LOCATION, FakeQloo, envelope, key
from tests.test_product import (  # noqa: F401  (fixtures below reuse the client)
    ADDED,
    add,
    client,  # noqa: F401
    profile,  # noqa: F401
)
from tests.test_venue_categories import CAFES


@pytest.fixture
def plain():
    return TestClient(main.app)


def test_a_form_post_larger_than_any_form_is_refused_before_it_is_read(plain):
    big = {"animal": "dog-02", "location": "park-slope", "text": "x" * 70_000}
    assert plain.post("/refine", data=big).status_code == 413


def test_a_post_from_another_site_is_refused(plain):
    data = {"animal": "dog-02", "location": "park-slope"}
    assert (
        plain.post("/runs", data=data, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    )
    other = {"origin": "https://elsewhere.example"}
    assert plain.post("/runs", data=data, headers=other).status_code == 403
    # The page's own form (same origin, or a browser that sends neither) goes through.
    same = {"sec-fetch-site": "same-origin"}
    assert plain.post("/runs", data=data, headers=same, follow_redirects=False).status_code != 403


def test_every_page_carries_the_security_headers(plain):
    headers = plain.get("/").headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "script-src 'self' https://unpkg.com" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_finished_runs_are_dropped_after_an_hour_and_the_list_is_bounded(monkeypatch):
    monkeypatch.setattr(runs, "RUNS", {})
    monkeypatch.setattr(runs, "MAX_RUNS", 3)

    def run(i, finished, age):
        log = StepLog()
        log.finished = finished
        log.finished_at = time.monotonic() - age if finished else None
        r = runs.Run(id=str(i), animal_id="dog-02", location_id="x", log=log)
        r.created = time.monotonic() - 9000  # started long ago: only the finish counts
        runs.RUNS[r.id] = r

    run(0, True, 4000)  # finished over an hour ago: dropped
    run(1, False, 0)  # still working: kept, however old
    for i in range(2, 6):
        run(i, True, 10)
    runs.prune_runs()
    assert "0" not in runs.RUNS and "1" in runs.RUNS
    assert len(runs.RUNS) == 3 and list(runs.RUNS)[-1] == "5"


def test_a_missing_page_is_a_page_for_a_browser_and_json_for_the_api(plain):
    page = plain.get("/runs/nope", headers={"accept": "text/html"})
    assert page.status_code == 404 and "<html" in page.text.lower()
    assert "a run is kept for an hour" in page.text
    api = plain.get("/api/runs/nope/events")
    assert api.status_code == 404 and api.headers["content-type"].startswith("application/json")


def test_a_refused_form_keeps_what_was_typed(client):  # noqa: F811
    response = add(client, facts="\n".join(f"fact {i}" for i in range(9)))
    assert response.status_code == 400
    assert f'value="{ADDED["look"]}"' in response.text and "fact 8" in response.text


def test_photos_beyond_the_memory_budget_are_refused(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(main, "PHOTO_BUDGET", 10)
    response = add(client, photo=b"\xff\xd8\xff\xe0 a photo of more than ten bytes")
    assert response.status_code == 400 and "too many photos" in response.text


def test_adding_animals_has_a_per_minute_allowance(client):  # noqa: F811
    # Refused attempts do not count (review of PR #46): five, then a valid one is added.
    for _ in range(5):
        assert add(client, species="bird").status_code == 400
    assert add(client).status_code == 303
    # Five added from one address in a minute (three per visit, so two visits), then 429,
    # with what was typed kept on the form.
    for _ in range(2):
        add(client)
    other = TestClient(main.app)
    assert [add(other).status_code for _ in range(3)] == [303, 303, 429]


def test_robots_and_the_favicon_are_served(plain):
    assert "Disallow: /api/" in plain.get("/robots.txt").text
    assert plain.get("/static/favicon.svg").status_code == 200


def deps(script):
    d = ProfileDeps(
        qloo=FakeQloo(script, twins=False), location=LOCATION, species="dog", log=StepLog()
    )
    d.titles_seen[DOG_SHOW] = Entity(
        id=DOG_SHOW, name="Example Dog Show", type="urn:entity:tv_show"
    )
    return d


def test_a_partial_list_of_places_is_not_picked_from():
    script = {
        key("recommend", venue_input([DOG_SHOW], LOCATION, True)): envelope(
            "recommend", "partial", results=CAFES
        )
    }
    d = deps(script)
    d.venue_filter = True
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    assert out["status"] == "unavailable: Qloo's list of places was partial"


def test_the_ais_own_lookups_and_venue_searches_are_capped():
    d = deps({})
    d.lookups = MAX_LOOKUPS
    out = look_up_title(SimpleNamespace(deps=d), "Another Show", "tv_show")
    assert out["status"].startswith("limit reached") and d.qloo.calls == []
    d.venue_searches = MAX_VENUE_SEARCHES
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    assert out["status"].startswith("limit reached") and d.qloo.calls == []


@pytest.mark.parametrize("ui", ["story", "warm", "classic"])
def test_no_page_needs_an_exception_to_the_content_security_policy(plain, ui):
    # Review of PR #46: the policy allows no inline script or style; this keeps it true.
    import re

    for path in (
        "/",
        "/result?animal=dog-02&location=park-slope",
        "/animals/new?location=park-slope",
    ):
        sep = "&" if "?" in path else "?"
        html = plain.get(f"{path}{sep}ui={ui}").text
        scripts = re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>", html)
        assert scripts == [], (path, scripts)
        assert not re.search(r"\sstyle=", html), path
        assert not re.search(r"\son[a-z]+=", html), path


def test_a_post_whose_origin_is_this_host_goes_through(plain):
    data = {"animal": "dog-02", "location": "park-slope"}
    same = {"origin": "http://testserver"}
    assert plain.post("/runs", data=data, headers=same, follow_redirects=False).status_code != 403


def test_the_api_docs_pages_are_off_and_the_schema_stays(plain):
    assert plain.get("/docs").status_code == 404 and plain.get("/redoc").status_code == 404
    assert plain.get("/openapi.json").status_code == 200


def test_a_partial_title_lookup_is_kept_with_a_note():
    answer = envelope(
        "describe",
        "partial",
        results=[{"entity_id": DOG_SHOW, "name": "Example Dog Show", "type": "urn:entity:tv_show"}],
    )
    d = deps({key("describe", {"entity": "Example Dog Show", "type": "tv_show"}): answer})
    out = look_up_title(SimpleNamespace(deps=d), "Example Dog Show", "tv_show")
    assert out == {"status": "found", "entity_id": DOG_SHOW, "name": "Example Dog Show"}
    assert any("was partial" in s.text for s in d.log.steps)
