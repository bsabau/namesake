"""Pet titles decided by Qloo (decision 22): the area's own pet-themed lists come first,
and a title stays only with Qloo's evidence for the area. Fake Qloo, invented data only."""

from app.agent.profile_agent import ProfileDeps, has_evidence, pet_lists
from app.agent.steps import StepLog
from app.profile import PET_TAGS, Entity, FoundIn
from app.views.build import name_badge, who_chose, why
from tests.qloo_fakes import (
    BASELINE,
    CAT_SHOW,
    DOG_SHOW,
    LOCATION,
    PET_VENUES,
    FakeQloo,
    cell,
    envelope,
    key,
    show,
)
from tests.test_agents import DRAFT, PLAN, Script, full_script, run
from tests.test_local_titles import (
    CAT_CAFE,
    PUPPY_SCHOOL,
    SPACE_OPERA,
    VERDICTS,
    FakeClassifier,
)

PET_LIST = [
    show(PUPPY_SCHOOL, "Example Puppy School", "A made-up cartoon about a puppy at school."),
    show(SPACE_OPERA, "Example Space Opera", "A made-up adventure among the stars."),
    show(CAT_CAFE, "Example Cat Cafe", "A made-up comedy set in a cafe with a resident cat."),
]


def pet_key(kind):
    return key(
        "recommend",
        {
            "target_type": kind,
            "signal_tags": PET_TAGS,
            "signal_tags_operator": "union",
            "signal_location": LOCATION.query,
            "limit": 20,
        },
    )


def deps(script, classifier=None) -> ProfileDeps:
    return ProfileDeps(
        qloo=FakeQloo(script),
        location=LOCATION,
        species="dog",
        log=StepLog(),
        baseline_titles={BASELINE: "Example Drama"},
        classifier=classifier,
    )


def test_qloos_pet_lists_come_from_the_area_and_the_pet_tags():
    d = deps(
        {
            pet_key("tv_show"): envelope("recommend", results=PET_LIST),
            pet_key("movie"): envelope("recommend", "empty"),
        },
        FakeClassifier(VERDICTS),
    )
    found = pet_lists(d)
    assert [t["name"] for t in found["tv_show"]["kept"]] == ["Example Puppy School"]
    assert [t["name"] for t in found["tv_show"]["unsure"]] == ["Example Cat Cafe"]
    assert found["tv_show"]["dropped"] == 1
    assert found["movie"]["status"].startswith("unavailable")
    assert found["book"]["status"].startswith("unavailable")  # not cached: no answer
    puppy = d.titles_seen[PUPPY_SCHOOL]
    assert puppy.found_in.by_tags and (puppy.found_in.position, puppy.found_in.out_of) == (1, 3)
    assert SPACE_OPERA not in d.titles_seen  # set aside by the classifier
    # Only cultural entities and the place go to Qloo.
    sent = d.qloo.calls[0][1]
    assert sent["signal_tags"] == PET_TAGS and sent["signal_location"] == LOCATION.query


def test_evidence_is_qloos_ranking_or_a_place_in_the_areas_lists():
    d = deps({})
    place = FoundIn(signal="x", kind="tv_show", position=2, out_of=20)
    d.titles_seen = {
        DOG_SHOW: Entity(id=DOG_SHOW, name="Dog", type="urn:entity:tv_show"),
        CAT_SHOW: Entity(id=CAT_SHOW, name="Cat", type="urn:entity:tv_show", found_in=place),
        CAT_CAFE: Entity(id=CAT_CAFE, name="Cafe", type="urn:entity:tv_show", listed_in=place),
        PUPPY_SCHOOL: Entity(id=PUPPY_SCHOOL, name="Puppy", type="urn:entity:tv_show"),
    }
    d.rank_order = [PUPPY_SCHOOL]
    assert [has_evidence(d, i) for i in (DOG_SHOW, CAT_SHOW, CAT_CAFE, PUPPY_SCHOOL)] == [
        False,
        True,
        True,
        True,
    ]


def refused_rank_script():
    script = full_script()
    q = LOCATION.query
    script[
        key(
            "rank",
            {"option_type": "tv_show", "options": [DOG_SHOW, CAT_SHOW], "signal_location": q},
        )
    ] = envelope(
        "rank",
        "error",
        error={"code": "QLOO_RATE_LIMIT", "layer": "api", "retryable": False, "recovery": "wait"},
    )
    script[pet_key("tv_show")] = envelope("recommend", results=PET_LIST[:1])
    script[
        key(
            "recommend",
            {"target_type": "place", "signals": [PUPPY_SCHOOL], "filter_location": q, "limit": 15},
        )
    ] = envelope("recommend", results=PET_VENUES)
    script[key("where_popular", {"entity": PUPPY_SCHOOL, "within": q, "limit": 20})] = envelope(
        "where_popular", results=[cell("dr5rks5", 40.6721, -73.9771, 0.8)]
    )
    return script


def test_the_ais_own_titles_stay_only_with_qloos_evidence(roster):
    # Hoboken, 18 October: the ranking was refused, and the AI's own titles led anyway.
    plan = {**PLAN, "titles": [{"entity_id": PUPPY_SCHOOL, "why": "a puppy"}, *PLAN["titles"]]}
    # The scripted listing names the left-out titles, so it is refused and falls back.
    script = Script([plan], [DRAFT, DRAFT], venue_titles=[DOG_SHOW, CAT_SHOW, PUPPY_SCHOOL])
    _, store, log = run(script, roster, qloo=FakeQloo(refused_rank_script()))
    profile = store.get_profile(LOCATION.id, "dog")
    assert [e.id for e in profile.pet_entities] == [PUPPY_SCHOOL]
    assert profile.venue_signals == [PUPPY_SCHOOL]  # the backed title, not the AI's first
    assert profile.left_out_titles == ["Example Dog Show", "Example Cat Show"]
    assert profile.titles_confirmed
    assert any(s.text.startswith("Left out Example Dog Show") for s in log.steps)
    assert "Code left out Example Dog Show and Example Cat Show: Qloo neither ranks them" in (
        who_chose(profile)
    )
    returned, _ = why(LOCATION, profile)
    assert returned[0].detail.startswith(
        "1st of 1 in Qloo's list of pet-themed TV shows people around Example Slope tend to like."
    )
    assert name_badge("pet", PUPPY_SCHOOL, profile) == (
        "Pet-themed title, in Qloo's pet-themed list for this area"
    )


def test_with_no_evidence_anywhere_the_ais_titles_stay_and_say_so(roster):
    script = refused_rank_script()
    del script[pet_key("tv_show")]
    _, store, _ = run(Script([PLAN], [DRAFT]), roster, qloo=FakeQloo(script))
    profile = store.get_profile(LOCATION.id, "dog")
    assert [e.id for e in profile.pet_entities] == [DOG_SHOW, CAT_SHOW]
    assert not profile.titles_confirmed and profile.left_out_titles == []
    assert "Qloo had no list or ranking that backs a pet title here" in who_chose(profile)


def test_the_ai_is_told_qloos_pet_titles_up_front(roster):
    seen = {}

    class Recording(Script):
        def __call__(self, messages, info):
            if "prompt" not in seen:
                seen["prompt"] = messages[0].parts[-1].content
            return super().__call__(messages, info)

    run(Recording([PLAN], [DRAFT]), roster, qloo=FakeQloo(refused_rank_script()))
    assert "Qloo's pet-themed titles for this area" in seen["prompt"]
    assert "Example Puppy School" in seen["prompt"]
