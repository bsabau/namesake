"""Decision 20: the area's lists as a source of pet titles, sorted by a classifier.

No test reaches Qloo or Jev: Qloo is a FakeQloo with hand-written envelopes, and Jev is
either a fake classifier or JevClassifier with a fake `post`.
"""

import json
from types import SimpleNamespace

from app.agent.profile_agent import (
    MAX_LOCAL_SEARCHES,
    ProfileDeps,
    ProfilePlan,
    check_plan,
    find_local_titles,
)
from app.agent.steps import StepLog
from app.classify import QUESTIONS, JevClassifier, bucket, classifier_from
from app.profile import Entity, FoundIn, LocationProfile, PetVerdict
from tests.qloo_fakes import (
    BASELINE,
    CAT_SHOW,
    DOG_SHOW,
    LOCATION,
    FakeQloo,
    envelope,
    key,
    show,
)
from tests.test_agents import DRAFT, PLAN, Script, call, full_script, run

# Invented titles that people around the area who like the dog show also like.
PUPPY_SCHOOL = "00000000-0000-4000-8000-000000000301"
CAT_CAFE = "00000000-0000-4000-8000-000000000302"
SPACE_OPERA = "00000000-0000-4000-8000-000000000303"
DOG_DOCS = "00000000-0000-4000-8000-000000000304"

LOCAL_LIST = [
    show(PUPPY_SCHOOL, "Example Puppy School", "A made-up cartoon about a puppy at school."),
    show(BASELINE, "Example Drama", "A made-up drama about a ranch."),
    show(CAT_CAFE, "Example Cat Cafe", "A made-up comedy set in a cafe with a resident cat."),
    show(SPACE_OPERA, "Example Space Opera", "A made-up adventure among the stars."),
    show(DOG_SHOW, "Example Dog Show", "Already proposed by the AI."),
]


def verdict(pets, dogs=0.1, cats=0.1, family=0.9, real_people=0.05) -> PetVerdict:
    return PetVerdict(pets=pets, dogs=dogs, cats=cats, family=family, real_people=real_people)


VERDICTS = {
    PUPPY_SCHOOL: verdict(0.97, dogs=0.95),
    CAT_CAFE: verdict(0.55, cats=0.7),
    SPACE_OPERA: verdict(0.05),
}


class FakeClassifier:
    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.asked: list[str] = []

    def classify(self, entity):
        self.asked.append(entity.id)
        return self.verdicts.get(entity.id)


def local_key(signal=DOG_SHOW, kind="tv_show"):
    return key(
        "recommend",
        {"target_type": kind, "signals": [signal], "signal_location": LOCATION.query, "limit": 20},
    )


def deps(classifier=None, answer=None) -> ProfileDeps:
    script = {local_key(): answer or envelope("recommend", results=LOCAL_LIST)}
    d = ProfileDeps(
        qloo=FakeQloo(script),
        location=LOCATION,
        species="dog",
        log=StepLog(),
        baseline_titles={BASELINE: "Example Drama"},
        classifier=classifier,
    )
    d.titles_seen[DOG_SHOW] = Entity(
        id=DOG_SHOW, name="Example Dog Show", type="urn:entity:tv_show"
    )
    return d


def ctx(d):
    return SimpleNamespace(deps=d)


# The classifier


def test_bucket_keeps_only_sure_family_pet_titles():
    assert bucket(verdict(0.9)) == "kept"
    assert bucket(verdict(0.9, family=0.3)) == "unsure"
    assert bucket(verdict(0.5)) == "unsure"
    assert bucket(verdict(0.2)) == "dropped"
    assert bucket(None) == "unsure"


def jev_answer(pets=0.97):
    answers = {q: {"type": "noul", "noul": 0.1} for q in QUESTIONS}
    answers["pets"]["noul"] = pets
    return {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1}}


def test_jev_sends_the_title_alone_and_caches_its_answer(tmp_path):
    calls = []

    def post(url, headers, body):
        calls.append((url, headers, json.loads(body)))
        return jev_answer()

    jev = JevClassifier("test-key", tmp_path / "c.sqlite", model="jev-x", post=post)
    title = Entity(
        id=PUPPY_SCHOOL,
        name="Example Puppy School",
        type="urn:entity:tv_show",
        description="A made-up cartoon.",
    )
    first = jev.classify(title)
    assert first.pets == 0.97 and first.model == "jev-test"
    url, headers, body = calls[0]
    assert url == "https://api.typesafe.ai/v1/systemone"
    assert headers["Authorization"] == "Bearer test-key"
    # Only the title as Qloo returned it: nothing about a visitor, an animal or a place.
    assert body["state"] == {
        "title": "Example Puppy School",
        "type": "tv_show",
        "description": "A made-up cartoon.",
    }
    assert body["model"] == "jev-x" and set(body["questions"]) == set(QUESTIONS)
    # Asked once: the second time comes from the cache.
    assert jev.classify(title) == first and len(calls) == 1


def test_a_failed_jev_call_leaves_the_title_to_the_ai_and_is_asked_again(tmp_path):
    calls = []

    def post(url, headers, body):
        calls.append(1)
        raise OSError("timed out")

    title = Entity(id=CAT_CAFE, name="Example Cat Cafe", type="urn:entity:tv_show")
    jev = JevClassifier("test-key", tmp_path / "c.sqlite", post=post)
    assert jev.classify(title) is None and jev.classify(title) is None
    assert len(calls) == 1  # down for the rest of this run
    # Nothing was cached, so the next run asks again.
    assert JevClassifier("test-key", tmp_path / "c.sqlite", post=post).classify(title) is None
    assert len(calls) == 2


def test_without_a_key_there_is_no_classifier(isolated_settings):
    assert classifier_from(isolated_settings) is None


# The tool


def test_the_classifier_keeps_drops_and_leaves_the_rest_to_the_ai():
    d = deps(FakeClassifier(VERDICTS))
    out = find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    assert [t["name"] for t in out["kept"]] == ["Example Puppy School"]
    assert [t["name"] for t in out["unsure"]] == ["Example Cat Cafe"]
    assert out["dropped"] == 1 and out["out_of"] == 5
    # The baseline show and the AI's own title are skipped, never offered again.
    assert BASELINE not in {t["entity_id"] for t in out["kept"] + out["unsure"]}
    # A dropped title cannot be chosen: check_plan accepts only titles_seen.
    assert SPACE_OPERA not in d.titles_seen
    puppy = d.titles_seen[PUPPY_SCHOOL]
    assert puppy.found_in == FoundIn(
        signal="Example Dog Show", kind="tv_show", position=1, out_of=5
    )
    assert puppy.verdict.pets == 0.97
    assert out["kept"][0]["classifier"]["about_pets"] == 0.97
    assert any("the classifier found 1 about pets" in s.text for s in d.log.steps)


def test_without_a_classifier_the_ai_judges_every_title():
    d = deps(None)
    out = find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    assert out["kept"] == [] and len(out["unsure"]) == 3 and out["dropped"] == 0
    assert "classifier" not in out["unsure"][0]
    assert any("no classifier" in s.text for s in d.log.steps)


def test_the_search_is_limited_per_run():
    d = deps(FakeClassifier(VERDICTS))
    for _ in range(MAX_LOCAL_SEARCHES):
        assert find_local_titles(ctx(d), DOG_SHOW, "tv_show")["status"] == "found"
    assert find_local_titles(ctx(d), DOG_SHOW, "tv_show")["status"].startswith("unavailable")


def test_a_partial_list_may_have_lost_the_area_and_is_not_used():
    d = deps(FakeClassifier(VERDICTS), envelope("recommend", "partial", results=LOCAL_LIST))
    out = find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    assert out["status"] == "unavailable: Qloo's list was partial"
    assert PUPPY_SCHOOL not in d.titles_seen


def test_a_title_must_be_looked_up_and_never_a_baseline_show():
    d = deps(None)
    assert "look the title up first" in find_local_titles(ctx(d), CAT_SHOW, "tv_show")["status"]
    d.titles_seen[BASELINE] = Entity(id=BASELINE, name="Example Drama", type="urn:entity:tv_show")
    assert "comparison uses" in find_local_titles(ctx(d), BASELINE, "tv_show")["status"]
    assert d.local_searches == 0


def test_an_identity_coded_title_is_refused_as_a_pet_title():
    d = deps(None)
    d.titles_seen[SPACE_OPERA] = Entity(
        id=SPACE_OPERA,
        name="Example Rally",
        type="urn:entity:tv_show",
        description="A made-up satire about communists and their dogs.",
    )
    d.venue_signals = [DOG_SHOW]
    plan = ProfilePlan(titles=[{"entity_id": SPACE_OPERA, "why": "dogs"}], venues=[])
    try:
        check_plan(ctx(d), plan)
    except Exception as exc:  # ModelRetry
        assert "coded to a religion, race or political identity" in str(exc)
    else:
        raise AssertionError("check_plan accepted an identity-coded title")


# End to end: the AI searches, keeps a local title, and ranks it with its own.


class LocalScript(Script):
    def __call__(self, messages, info):
        done = {
            p.tool_name
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", "") == "tool-return"
        }
        tools = {t.name for t in info.function_tools}
        if "find_local_titles" in tools and "look_up_title" in done:
            if "find_local_titles" not in done:
                return call("find_local_titles", entity_id=DOG_SHOW, kind="tv_show")
            if "rank_titles" not in done:
                return call(
                    "rank_titles", entity_ids=[DOG_SHOW, CAT_SHOW, PUPPY_SCHOOL], kind="tv_show"
                )
        return super().__call__(messages, info)


def test_a_kept_local_title_joins_the_ranking_and_shows_its_evidence(roster, monkeypatch):
    import app.agent.pipeline as pipeline

    script = full_script()
    script[local_key()] = envelope("recommend", results=LOCAL_LIST)
    ranked = [
        {"entity_id": PUPPY_SCHOOL, "name": "Example Puppy School", "type": "urn:entity:tv_show"},
        {"entity_id": CAT_SHOW, "name": "Example Cat Show", "type": "urn:entity:tv_show"},
        {"entity_id": DOG_SHOW, "name": "Example Dog Show", "type": "urn:entity:tv_show"},
    ]
    script[
        key(
            "rank",
            {
                "option_type": "tv_show",
                "options": [DOG_SHOW, CAT_SHOW, PUPPY_SCHOOL],
                "signal_location": LOCATION.query,
            },
        )
    ] = envelope("rank", results=ranked)
    plan = {**PLAN, "titles": [*PLAN["titles"], {"entity_id": PUPPY_SCHOOL, "why": "a puppy"}]}
    real_run = pipeline.run_pipeline

    async def with_classifier(*args, **kwargs):
        return await real_run(*args, **kwargs, classifier=FakeClassifier(VERDICTS))

    monkeypatch.setattr("tests.test_agents.run_pipeline", with_classifier)
    _, store, log = run(LocalScript([plan], [DRAFT]), roster, qloo=FakeQloo(script))
    profile = store.get_profile(LOCATION.id, "dog")
    assert [e.id for e in profile.pet_entities] == [PUPPY_SCHOOL, CAT_SHOW, DOG_SHOW]
    puppy = profile.pet_entities[0]
    assert puppy.found_in.signal == "Example Dog Show" and puppy.verdict.pets == 0.97
    assert any("Asking Qloo which TV shows people around" in s.text for s in log.steps)


def test_the_page_keeps_qloos_list_apart_from_the_classifiers_reading(roster):
    from app.views.build import build_result_view, name_badge, why

    puppy = Entity(
        id=PUPPY_SCHOOL,
        name="Example Puppy School",
        type="urn:entity:tv_show",
        description="A made-up cartoon about a puppy at school.",
        why="a puppy at school",
        found_in=FoundIn(signal="Example Dog Show", kind="tv_show", position=3, out_of=20),
        verdict=verdict(0.97, dogs=0.95),
    )
    profile = LocationProfile(
        location_id=LOCATION.id, species="dog", pet_entities=[puppy], made_by="agent"
    )
    returned, reading = why(LOCATION, profile)
    qloo = next(i for i in returned if i.title.startswith("Example Puppy School"))
    assert qloo.detail.startswith(
        "3rd of 20 in Qloo's list of TV shows people around Example Slope who like Example "
        "Dog Show tend to like."
    )
    # The classifier's numbers are our reading, never in Qloo's column.
    assert not any("TypeSafe" in i.detail for i in returned)
    sorted_ = next(i for i in reading if i.title == "How Example Puppy School was sorted")
    assert "TypeSafe's Jev" in sorted_.detail and "about pets 0.97" in sorted_.detail
    who = next(i for i in reading if i.title == "Who chose")
    assert "searched Qloo's lists" in who.detail
    assert name_badge("pet", PUPPY_SCHOOL, profile) == (
        "Pet-themed title, liked here by fans of Example Dog Show"
    )
    view = build_result_view(roster.get("dog-02"), LOCATION, profile)
    assert "TypeSafe" in view.credits.classifier


def test_a_page_without_classified_titles_has_no_classifier_credit(roster):
    from app.views.build import build_result_view

    view = build_result_view(roster.get("dog-02"), LOCATION, LocationProfile(location_id="x"))
    assert view.credits.classifier is None


# Review fixes (Codex, muse, Flash)


def test_a_broken_or_odd_answer_never_stops_a_run(tmp_path):
    import http.client

    title = Entity(id=PUPPY_SCHOOL, name="Example Puppy School", type="urn:entity:tv_show")
    for failure in (http.client.IncompleteRead(b""), RuntimeError("anything")):

        def post(url, headers, body, failure=failure):
            raise failure

        assert JevClassifier("k", tmp_path / "a.sqlite", post=post).classify(title) is None
    # NaN, infinity and out-of-range answers are refused, never cached.
    for bad in ("NaN", "inf", 1.5, -0.1):
        answer = jev_answer()
        answer["answers"]["family"]["noul"] = bad
        jev = JevClassifier("k", tmp_path / "b.sqlite", post=lambda u, h, b, a=answer: a)
        assert jev.classify(title) is None
    # A cache the classifier cannot open costs the title, not the run.
    (tmp_path / "dir.sqlite").mkdir()
    jev = JevClassifier("k", tmp_path / "dir.sqlite", post=lambda u, h, b: jev_answer())
    assert jev.classify(title) is None


def test_a_new_model_or_description_asks_again(tmp_path):
    calls = []

    def post(url, headers, body):
        calls.append(json.loads(body)["state"]["description"])
        return jev_answer()

    db = tmp_path / "c.sqlite"
    title = Entity(
        id=PUPPY_SCHOOL, name="Example Puppy School", type="urn:entity:tv_show", description="One."
    )
    JevClassifier("k", db, post=post).classify(title)
    JevClassifier("k", db, post=post).classify(title)
    JevClassifier("k", db, model="jev-2", post=post).classify(title)
    JevClassifier("k", db, post=post).classify(title.model_copy(update={"description": "Two."}))
    assert calls == ["One.", "One.", "Two."]


def test_only_an_https_classifier_is_used(isolated_settings, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(isolated_settings, "typesafe_api_key", SecretStr("k"))
    assert classifier_from(isolated_settings) is not None
    monkeypatch.setattr(isolated_settings, "typesafe_base_url", "http://example.test/v1")
    assert classifier_from(isolated_settings) is None


def test_after_a_failed_call_only_saved_answers_are_used(tmp_path):
    calls = []

    def post(url, headers, body):
        title = json.loads(body)["state"]["title"]
        calls.append(title)
        if title == "Example Cat Cafe" and len(calls) > 1:
            raise OSError("timed out")
        return jev_answer()

    db = tmp_path / "c.sqlite"
    cafe = Entity(id=CAT_CAFE, name="Example Cat Cafe", type="urn:entity:tv_show")
    puppy = Entity(id=PUPPY_SCHOOL, name="Example Puppy School", type="urn:entity:tv_show")
    JevClassifier("k", db, post=post).classify(puppy)  # saved by an earlier run
    jev = JevClassifier("k", db, post=post)
    assert jev.classify(cafe) is None and jev.down
    space = Entity(id=SPACE_OPERA, name="Example Space Opera", type="urn:entity:tv_show")
    assert jev.classify(space) is None  # not asked: Jev is down for this run
    assert jev.classify(puppy).pets == 0.97  # but saved answers still count
    assert calls == ["Example Puppy School", "Example Cat Cafe"]


def test_a_down_classifier_is_named_in_the_step_log():
    class Down(FakeClassifier):
        def classify(self, entity):
            return None

    d = deps(Down({}))
    out = find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    assert len(out["unsure"]) == 3
    assert any("did not answer for 3" in s.text for s in d.log.steps)


def test_without_a_classifier_a_search_starts_from_the_ais_own_titles():
    d = deps(None)
    find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    status = find_local_titles(ctx(d), CAT_CAFE, "movie")["status"]
    assert status.endswith("with no classifier, search only with your own titles")


def test_an_unresolved_area_is_named_as_such():
    d = deps(None, envelope("recommend", "needs_input"))
    status = find_local_titles(ctx(d), DOG_SHOW, "tv_show")["status"]
    assert status == f"unavailable: Qloo could not tell which place {LOCATION.query!r} means"


def test_a_search_widens_only_from_a_title_known_to_be_about_pets():
    d = deps(FakeClassifier(VERDICTS))
    find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    assert (
        "without the classifier keeping it"
        in find_local_titles(ctx(d), CAT_CAFE, "movie")["status"]
    )
    # A kept title may seed the next search.
    d.qloo = FakeQloo({local_key(PUPPY_SCHOOL, "movie"): envelope("recommend", results=[])})
    assert "without" not in find_local_titles(ctx(d), PUPPY_SCHOOL, "movie")["status"]


def test_looking_a_found_title_up_again_keeps_its_evidence():
    from app.agent.profile_agent import look_up_title
    from tests.qloo_fakes import describe_ok

    d = deps(FakeClassifier(VERDICTS))
    find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    d.qloo = FakeQloo(
        {
            key("describe", {"entity": "Example Puppy School", "type": "tv_show"}): describe_ok(
                PUPPY_SCHOOL, "Example Puppy School"
            )
        }
    )
    look_up_title(ctx(d), "Example Puppy School", "tv_show")
    again = d.titles_seen[PUPPY_SCHOOL]
    assert again.found_in.signal == "Example Dog Show" and again.verdict.pets == 0.97


def test_a_title_the_classifier_marks_as_about_real_people_gives_only_animal_names():
    from app.agent.listing_agent import NameOption, screen_names
    from tests.test_agents import DRAFT

    show_ = Entity(
        id=DOG_DOCS,
        name="Example Dog Days",
        type="urn:entity:tv_show",
        description="A made-up series.",
        verdict=verdict(0.95, real_people=0.9),
    )
    host = NameOption(
        **{**DRAFT["names"][0], "source": "pet", "entity_id": DOG_DOCS, "role": "character"}
    )
    problems = screen_names([host], {DOG_DOCS: show_}, False)
    assert any("the classifier scores it so" in p for p in problems)
    dog = NameOption(**{**DRAFT["names"][0], "source": "pet", "entity_id": DOG_DOCS})
    assert screen_names([dog], {DOG_DOCS: show_}, False) == []


def test_a_ranked_found_title_shows_both_badges():
    from app.views.build import name_badge

    puppy = Entity(
        id=PUPPY_SCHOOL,
        name="Example Puppy School",
        type="urn:entity:tv_show",
        found_in=FoundIn(signal="Example Dog Show", kind="tv_show", position=1, out_of=20),
    )
    profile = LocationProfile(location_id="x", pet_entities=[puppy], ranked=[PUPPY_SCHOOL])
    assert name_badge("pet", PUPPY_SCHOOL, profile) == (
        "Pet-themed title, ranked 1st of 1 here by Qloo; liked here by fans of Example Dog Show"
    )


# The classifier reaches the pipeline (Flash, PR #7 re-check)


def test_runs_pass_the_configured_classifier_to_both_pipelines(
    roster, isolated_settings, monkeypatch
):
    import asyncio

    import app.runs as runs

    sentinel = FakeClassifier({})
    seen: dict[str, object] = {}

    async def fake_pipeline(*args, **kwargs):
        seen["run_pipeline"] = kwargs.get("classifier")

    async def fake_litter(*args, **kwargs):
        seen["run_litter"] = kwargs.get("classifier")

    monkeypatch.setattr(runs, "classifier_from", lambda settings: sentinel)
    monkeypatch.setattr(runs, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(runs, "run_litter", fake_litter)

    async def go():
        run = await runs.start_run(roster.get("dog-02"), LOCATION, isolated_settings)
        await run.task
        litter = await runs.start_litter_run(roster.litters[0], LOCATION, isolated_settings)
        await litter.task

    asyncio.run(go())
    assert seen == {"run_pipeline": sentinel, "run_litter": sentinel}


def test_a_found_title_with_qloos_generic_type_gets_the_kind_asked_for():
    generic = [{**r, "type": "urn:entity"} for r in LOCAL_LIST]
    d = deps(FakeClassifier(VERDICTS), envelope("recommend", results=generic))
    find_local_titles(ctx(d), DOG_SHOW, "tv_show")
    assert d.titles_seen[PUPPY_SCHOOL].type == "urn:entity:tv_show"
