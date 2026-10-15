"""The contract every UI folder must meet: each screen renders the required elements.

A new UI under `app/ui/` is picked up automatically and must pass this test.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.profile import build_profile
from tests.qloo_fakes import SEEDS, FakeQloo, standard_script

REQUIRED = {
    "start": ["map", "photo-credit", "qloo-credit"],
    "working": ["working", "steps", "status", "photo-credit", "qloo-credit"],
    "result": ["name", "qloo-returned", "our-reading", "map", "photo-credit", "qloo-credit"],
}


@pytest.fixture
def client(monkeypatch):
    # Pages read the profile through this function; give them a synthetic one.
    def fake_profile(location, species):
        from tests.qloo_fakes import LOCATION

        return build_profile(FakeQloo(standard_script()), LOCATION.model_copy(), SEEDS)

    monkeypatch.setattr(main, "location_profile", fake_profile)
    return TestClient(main.app)


def test_there_is_at_least_one_ui():
    assert "classic" in main.UIS


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


@pytest.mark.parametrize("ui", main.UIS)
def test_ui_folders_never_reach_for_data(ui):
    # A UI renders view models only: no fetches outside the app's own /api/.
    for path in (main.UI_ROOT / ui).rglob("*"):
        if path.suffix in {".html", ".js"}:
            text = path.read_text(encoding="utf-8")
            for call in ["qloo exec", "qloo mcp", "/v2/", "hackathon.api"]:
                assert call not in text, f"{path.name} reaches for Qloo: {call}"
            assert "fetch(" not in text or "/api/" in text


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
