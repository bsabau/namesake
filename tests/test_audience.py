"""Who tends to like each name's title (app/audience.py, decision 31).

Synthetic envelopes and fake Qloo only; no test reaches Qloo or a model.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import main as app_main
from app.agent.listing_agent import ListingDraft
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.audience import (
    LEAN,
    NOTE,
    TitleAudience,
    add_audiences,
    ask_audience,
    audience_line,
)
from app.qloo.envelope import Envelope
from app.store import Store
from app.views.build import name_view
from tests.qloo_fakes import CAT_SHOW, DOG_SHOW, FakeQloo, envelope, key, standard_script
from tests.test_agents import DRAFT, PLAN, Script, full_script, run

FIXTURE = Path(__file__).parent / "fixtures" / "qloo" / "synthetic"


def demographics(entity_id=DOG_SHOW, age=None, gender=None) -> Envelope:
    return envelope(
        "audience_demographics",
        results=[{"entity_id": entity_id, "query": {"age": age or {}, "gender": gender or {}}}],
    )


def fake(**answers: Envelope) -> FakeQloo:
    return FakeQloo(
        {key("audience_demographics", {"entity": i}): e for i, e in answers.items()}, twins=False
    )


def test_the_fixture_reads_as_a_title_audience():
    env = Envelope.parse(json.loads((FIXTURE / "audience_demographics__ok.json").read_text()))
    audience = ask_audience(fake(**{DOG_SHOW: env}), DOG_SHOW)
    assert audience.age["45_to_54"] == 0.4 and audience.gender == {"male": -0.2, "female": 0.2}


def test_only_known_bands_and_numbers_are_kept():
    env = demographics(age={"35_to_44": 0.3, "made_up": 0.9, "45_to_54": "high"},
                       gender={"female": True, "male": 0.2})  # fmt: skip
    audience = ask_audience(fake(**{DOG_SHOW: env}), DOG_SHOW)
    assert audience.age == {"35_to_44": 0.3} and audience.gender == {"male": 0.2}


def test_no_answer_means_no_audience():
    assert ask_audience(fake(), DOG_SHOW) is None  # not cached while live calls are off
    empty = envelope("audience_demographics", results=[])
    assert ask_audience(fake(**{DOG_SHOW: empty}), DOG_SHOW) is None
    failure = {"code": "X", "layer": "api", "retryable": False, "recovery": ""}
    error = envelope("audience_demographics", "error", error=failure)
    assert ask_audience(fake(**{DOG_SHOW: error}), DOG_SHOW) is None
    other = demographics(entity_id=CAT_SHOW, age={"35_to_44": 0.5})
    assert ask_audience(fake(**{DOG_SHOW: other}), DOG_SHOW) is None


def test_an_answer_of_an_unknown_shape_is_no_answer():
    # Codex: a `query` that was not a dict raised, and the run lost its listing; flash
    # and muse: an answer with neither age nor gender was kept as if Qloo had answered.
    for results in (
        [{"entity_id": DOG_SHOW, "query": "unavailable"}],
        [{"entity_id": DOG_SHOW, "age": {"35_to_44": 0.4}}],
        [{"entity_id": DOG_SHOW, "query": {"age": {}, "gender": {}}}],
    ):
        env = envelope("audience_demographics", results=results)
        assert ask_audience(fake(**{DOG_SHOW: env}), DOG_SHOW) is None, results


def test_the_line_names_only_clear_leans_toward_a_group():
    age = {"35_to_44": 0.19, "45_to_54": 0.35, "55_and_older": -0.75}
    both = TitleAudience(entity_id=DOG_SHOW, age=age, gender={"male": -0.16, "female": 0.16})
    assert audience_line("Example Dog Show", both) == (
        "Fans of Example Dog Show lean toward ages 35 to 44 (+0.19) and 45 to 54 (+0.35), "
        "and are more often women (+0.16), across all of Qloo's audiences"
    )
    ages = TitleAudience(entity_id=DOG_SHOW, age={"24_and_younger": 0.39, "25_to_29": 0.12,
                         "45_to_54": 0.5, "55_and_older": 0.42}, gender={"male": 0.01})  # fmt: skip
    assert audience_line("X", ages) == (
        "Fans of X lean toward ages 24 and under (+0.39), 45 to 54 (+0.50) and 55 and over "
        "(+0.42), across all of Qloo's audiences"
    )
    men = TitleAudience(entity_id=DOG_SHOW, gender={"male": 0.75, "female": -0.75})
    assert (
        audience_line("X", men)
        == "Fans of X are more often men (+0.75), across all of Qloo's audiences"
    )
    # Leans away from a group, or too faint, say nothing.
    faint = TitleAudience(entity_id=DOG_SHOW, age={"35_to_44": LEAN - 0.01, "55_and_older": -0.9})
    assert audience_line("X", faint) is None and audience_line("X", None) is None


def saved(audiences=None) -> ListingResult:
    return ListingResult(
        animal_id="dog-02",
        location_id="park-slope",
        checks_version=CHECKS_VERSION,
        draft=ListingDraft.model_validate(DRAFT),
        audiences=audiences or {},
    )


def test_each_title_is_asked_once_and_a_known_one_not_again():
    result = saved({CAT_SHOW: TitleAudience(entity_id=CAT_SHOW, age={"25_to_29": 0.3})})
    qloo = fake(**{DOG_SHOW: demographics(age={"35_to_44": 0.4})})
    log = StepLog()
    assert add_audiences(result, qloo, log)
    assert qloo.calls == [("audience_demographics", {"entity": DOG_SHOW})]
    assert set(result.audiences) == {DOG_SHOW, CAT_SHOW}
    assert [s.text for s in log.steps] == [
        "Asking Qloo who tends to like the title the names come from"
    ]


def test_a_title_qloo_has_nothing_for_is_noted_and_left_out():
    result = saved()
    log = StepLog()
    assert not add_audiences(result, fake(**{DOG_SHOW: demographics(age={"35_to_44": 0.4})}), log)
    assert set(result.audiences) == {DOG_SHOW}
    assert log.steps[-1].text == "Qloo had no audience for 1 of them"


def test_a_run_saves_the_audiences_and_the_page_shows_them(roster):
    script = full_script()
    script[key("audience_demographics", {"entity": DOG_SHOW})] = demographics(
        age={"45_to_54": 0.35}, gender={"female": 0.16}
    )
    result, store, log = run(Script([PLAN], [DRAFT]), roster, qloo=FakeQloo(script))
    assert set(result.audiences) == {DOG_SHOW}
    assert store.get_listing("dog-02", result.location_id).audiences == result.audiences
    assert any("who tends to like" in s.text for s in log.steps)

    profile = store.get_profile(result.location_id, "dog")
    view = name_view(result, profile, "text")
    dog, cat = view.options[0], view.options[1]
    assert dog.audience.startswith("Fans of Example Dog Show lean toward ages 45 to 54")
    assert cat.audience is None and view.audience_note == NOTE


class Failing(FakeQloo):
    """Answers everything as scripted, except that the audience call fails oddly."""

    def run(self, operation, input_):
        if operation == "audience_demographics":
            self.calls.append((operation, input_))
            raise RuntimeError("database is locked")
        return super().run(operation, input_)


def test_a_failing_audience_call_never_costs_the_checked_listing(roster):
    # muse and flash: an error other than ReplayMiss or QlooExecError escaped, and the
    # listing, already written and checked, was never saved.
    result, store, log = run(Script([PLAN], [DRAFT]), roster, qloo=Failing(full_script()))
    assert result.draft is not None and result.audiences == {}
    assert store.get_listing("dog-02", result.location_id).draft == result.draft
    assert any(s.text.startswith("Qloo had no audience") for s in log.steps)


def test_each_litter_member_keeps_its_titles_audience(roster):
    # flash: the litter, one of the demo's two examples, had no test of this step.
    import asyncio

    from pydantic_ai.models.function import FunctionModel

    from app.agent.pipeline import run_litter
    from tests.qloo_fakes import LOCATION, SEEDS
    from tests.test_product import _db, litter_answers

    first = roster.get("dog-02")
    members = [first, first.model_copy(update={"id": "dog-02b"})]
    answers = full_script()
    answers[key("audience_demographics", {"entity": DOG_SHOW})] = demographics(
        age={"45_to_54": 0.35}
    )
    store = Store(_db())
    script = Script([PLAN], litter_answers())
    results = asyncio.run(
        run_litter(
            members,
            LOCATION,
            qloo=FakeQloo(answers),
            store=store,
            seeds=SEEDS,
            model_factory=lambda: FunctionModel(script),
            log=StepLog(),
        )
    )
    assert all(DOG_SHOW in r.audiences for r in results)
    assert DOG_SHOW in store.get_listing("dog-02b", LOCATION.id).audiences


def test_no_line_without_the_titles_own_name(roster):
    # flash: with the title unknown, the line would have named a character as the title.
    result, store, _ = run(Script([PLAN], [DRAFT]), roster)
    unknown = "00000000-0000-4000-8000-000000000999"
    first = result.draft.names[0].model_copy(update={"entity_id": unknown})
    result.draft = result.draft.model_copy(update={"names": [first, *result.draft.names[1:]]})
    result.audiences = {unknown: TitleAudience(entity_id=unknown, age={"45_to_54": 0.4})}
    view = name_view(result, store.get_profile(result.location_id, "dog"), "text")
    assert view.options[0].audience is None and view.audience_note == ""


def test_the_store_merges_audiences_only_onto_the_same_draft():
    # Codex: reading the latest listing and saving it were separate steps.
    store = Store(app_main.get_settings().cache_db)
    store.put_listing(saved())
    asked = saved({DOG_SHOW: TitleAudience(entity_id=DOG_SHOW, age={"35_to_44": 0.4})})
    assert store.merge_audiences(asked)
    assert not store.merge_audiences(asked)  # nothing new
    other = asked.model_copy(update={"draft": asked.draft.model_copy(
        update={"names": asked.draft.names[::-1]})})  # fmt: skip
    other.audiences = {CAT_SHOW: TitleAudience(entity_id=CAT_SHOW, gender={"female": 0.3})}
    assert not store.merge_audiences(other)
    assert set(store.get_listing("dog-02", "park-slope").audiences) == {DOG_SHOW}


def test_without_audiences_the_page_says_nothing_about_them(roster):
    result, store, _ = run(Script([PLAN], [DRAFT]), roster)
    view = name_view(result, store.get_profile(result.location_id, "dog"), "text")
    assert all(o.audience is None for o in view.options) and view.audience_note == ""


def test_every_skin_labels_the_line_as_qloo(roster, monkeypatch):
    from app.profile import build_profile
    from tests.qloo_fakes import LOCATION, SEEDS

    profile = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    monkeypatch.setattr(app_main, "location_profile", lambda location, species: profile)
    audience = TitleAudience(entity_id=DOG_SHOW, age={"45_to_54": 0.35})
    Store(app_main.get_settings().cache_db).put_listing(saved({DOG_SHOW: audience}))
    client = TestClient(app_main.app)
    for ui in app_main.UIS:
        html = client.get(
            "/result", params={"animal": "dog-02", "location": "park-slope", "ui": ui}
        ).text
        line = next(x for x in html.splitlines() if "lean toward ages 45 to 54" in x)
        assert 'class="evidence"' in line and "<span>Qloo" in line, ui
        assert "plays a part in choosing names" in html, ui


def test_the_backfill_fills_saved_listings_once(monkeypatch, capsys):
    import app.runs
    from app.audience import main

    store = Store(app_main.get_settings().cache_db)
    store.put_listing(saved())
    qloo = fake(**{DOG_SHOW: demographics(age={"35_to_44": 0.4}),
                   CAT_SHOW: demographics(entity_id=CAT_SHOW, gender={"female": 0.3})})  # fmt: skip
    monkeypatch.setattr(app.runs, "qloo_client", lambda settings: qloo)
    monkeypatch.setattr("sys.argv", ["audience"])
    main()
    assert set(store.get_listing("dog-02", "park-slope").audiences) == {DOG_SHOW, CAT_SHOW}
    out = capsys.readouterr().out
    assert "Listings complete: 1; with a title Qloo had nothing for: 0" in out
    main()
    assert len(qloo.calls) == 2  # nothing asked twice


def backfill(monkeypatch, qloo):
    import app.runs
    from app.audience import main

    monkeypatch.setattr(app.runs, "qloo_client", lambda settings: qloo)
    monkeypatch.setattr("sys.argv", ["audience"])
    main()


def test_the_backfill_leaves_a_listing_from_before_the_checks_changed(monkeypatch):
    # muse and flash: its next visitor's run rewrites it, so asking would be wasted.
    store = Store(app_main.get_settings().cache_db)
    old = saved()
    old.checks_version = CHECKS_VERSION - 1
    store.put_listing(old)
    qloo = fake(**{DOG_SHOW: demographics(age={"35_to_44": 0.4})})
    backfill(monkeypatch, qloo)
    assert qloo.calls == []
    kept = store.get_listing("dog-02", "park-slope", current_only=False)
    assert kept.checks_version == CHECKS_VERSION - 1 and kept.audiences == {}


def test_the_backfill_never_writes_over_a_listing_rewritten_meanwhile(monkeypatch, capsys):
    # Codex and flash: it read every listing first and wrote each back whole.
    store = Store(app_main.get_settings().cache_db)
    store.put_listing(saved())
    newer = saved()
    newer.draft = newer.draft.model_copy(update={"names": newer.draft.names[::-1]})

    class Rewriting(FakeQloo):
        def run(self, operation, input_):
            store.put_listing(newer)  # a visitor's run lands while Qloo is asked
            return super().run(operation, input_)

    qloo = Rewriting(
        {key("audience_demographics", {"entity": DOG_SHOW}): demographics(age={"35_to_44": 0.4})},
        twins=False,
    )
    backfill(monkeypatch, qloo)
    kept = store.get_listing("dog-02", "park-slope")
    assert kept.draft == newer.draft and kept.audiences == {}
    assert "dog-02 at park-slope: left alone, a run rewrote it meanwhile" in capsys.readouterr().out
