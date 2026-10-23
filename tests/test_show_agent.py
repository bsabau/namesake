"""What a saved result shows of the agent's own work (the final audits, 19 October): the
searches it chose, its Qloo calls in the Why panel, the run's step log, and a way to start
a run where there is no listing yet."""

from fastapi.testclient import TestClient

from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import Step
from app.main import app
from app.profile import Entity
from app.views.build import build_result_view, name_badge
from tests.qloo_fakes import LOCATION
from tests.test_agents import DRAFT, PLAN, Script
from tests.test_agents import run as run_pipeline_with
from tests.test_views import agent_profile


def test_a_saved_runs_steps_are_on_its_result_each_marked_by_who_did_it(roster):
    listing = ListingResult(
        animal_id="dog-02",
        location_id=LOCATION.id,
        checks_version=CHECKS_VERSION,
        steps=[
            Step(kind="qloo", text="Asking Qloo", at=0.0, actor="qloo"),
            Step(kind="decision", text="Kept 2 titles", at=1.0, actor="ai"),
            Step(kind="check", text="Listing checked", at=2.0),
        ],
    )
    view = build_result_view(roster.get("dog-02"), LOCATION, agent_profile(), listing)
    assert [(s.actor, s.label) for s in view.run_steps] == [
        ("qloo", "Qloo"),
        ("ai", "Namesake's AI"),
        ("code", "Code"),
    ]
    assert view.write_label is None


def test_with_no_listing_the_result_offers_a_run(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, agent_profile(), None)
    assert view.run_steps == []
    assert view.write_label == "Write her story with Namesake's AI"


def test_the_story_skin_renders_the_write_button_with_no_listing():
    # The test cache is empty, so there is no listing for this animal here.
    page = TestClient(app).get("/result", params={"animal": "dog-03", "location": "park-slope"})
    assert page.status_code == 200
    html = page.text
    assert 'data-role="write"' in html and 'form="write-form"' in html
    assert 'action="/runs"' in html and 'name="animal" value="dog-03"' in html
    assert 'data-role="run-steps"' not in html


def test_a_local_taste_name_shows_its_place_in_qloos_list():
    p = agent_profile()
    p.local_tastes = [
        Entity(id="a", name="Example Drama", type="urn:entity:tv_show"),
        Entity(id="b", name="Example Comedy", type="urn:entity:tv_show"),
    ]
    assert name_badge("local", "b", p) == (
        "Watched locally: 2nd of 2 in Qloo's list of what people here tend to watch"
    )
    assert name_badge("local", "zzz", p) == (
        "Not among the titles Qloo listed as what people here tend to watch"
    )


def test_the_ais_own_qloo_calls_reach_the_why_panel(roster):
    result, store, log = run_pipeline_with(Script([PLAN], [DRAFT]), roster)
    profile = store.get_profile(LOCATION.id, "dog")
    purposes = [c.purpose for c in profile.calls]
    assert any("a title Namesake's AI proposed" in p for p in purposes)
    assert any(c.operation == "rank" for c in profile.calls)
    view = build_result_view(roster.get("dog-02"), LOCATION, profile, result)
    assert any(i.title == "qloo describe" for i in view.qloo_returned)


def test_a_step_saved_before_actors_gets_the_one_its_kind_implies():
    old = {"at": 0.0, "kind": "qloo", "text": "Asking Qloo"}
    assert Step.model_validate(old).actor == "qloo"
    assert Step.model_validate({**old, "kind": "decision"}).actor == "ai"
    assert Step.model_validate({**old, "kind": "note"}).actor == "code"
    assert Step.model_validate({**old, "actor": "classifier"}).actor == "classifier"


def test_finishing_a_profile_keeps_the_calls_behind_its_titles(roster):
    from app.profile import QlooCall, finish_profile
    from tests.qloo_fakes import SEEDS, FakeQloo, standard_script

    result, store, log = run_pipeline_with(Script([PLAN], [DRAFT]), roster)
    old = store.get_profile(LOCATION.id, "dog")
    old.calls.append(QlooCall(operation="recommend", purpose="renamed", status="ok", results=3,
                              behind_titles=True))  # fmt: skip
    new = finish_profile(old, LOCATION.model_copy(), FakeQloo(standard_script()), SEEDS)
    assert new is not None and any(c.purpose == "renamed" for c in new.calls)
    view = build_result_view(roster.get("dog-02"), LOCATION, new, result)
    assert not any("1 results" in i.detail for i in view.qloo_returned)


def test_the_story_skin_renders_a_saved_runs_steps(monkeypatch, roster):
    # Review of PR #45: only the absence of the log was tested.
    from app import main
    from app.store import Store

    listing = ListingResult(
        animal_id="dog-03",
        location_id="park-slope",
        checks_version=CHECKS_VERSION,
        steps=[Step(kind="qloo", text="Asking Qloo which shows", at=0.0)],
    )
    Store(main.get_settings().cache_db).put_listing(listing)
    html = (
        TestClient(app).get("/result", params={"animal": "dog-03", "location": "park-slope"}).text
    )
    assert 'data-role="run-steps"' in html and "Asking Qloo which shows" in html
    assert 'data-role="write"' not in html
