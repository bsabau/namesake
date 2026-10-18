"""Pet titles decided by Qloo (decision 22): the area's own pet-themed lists come first,
and a title stays only with Qloo's evidence for the area. Fake Qloo, invented data only."""

from types import SimpleNamespace

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
    assert "None of the titles kept has Qloo's ranking or a place in the area's lists" in (
        who_chose(profile)
    )


def test_the_ai_is_told_qloos_pet_titles_up_front(roster):
    seen = {}

    class Recording(Script):
        def __call__(self, messages, info):
            if "prompt" not in seen:
                seen["prompt"] = messages[0].parts[-1].content
            return super().__call__(messages, info)

    plan = {**PLAN, "titles": [{"entity_id": PUPPY_SCHOOL, "why": "a puppy"}, *PLAN["titles"]]}
    script = Recording([plan], [DRAFT, DRAFT], venue_titles=[PUPPY_SCHOOL, DOG_SHOW, CAT_SHOW])
    run(script, roster, qloo=FakeQloo(refused_rank_script()))
    assert "Qloo's pet-themed titles for this area" in seen["prompt"]
    assert "Example Puppy School" in seen["prompt"]


def test_a_plan_that_ignores_every_title_qloo_backs_is_sent_back():
    from app.agent.profile_agent import ProfilePlan, check_plan

    d = deps({})
    place = FoundIn(signal="Qloo's pet tags", kind="tv_show", position=1, out_of=3, by_tags=True)
    d.titles_seen = {
        PUPPY_SCHOOL: Entity(
            id=PUPPY_SCHOOL, name="Example Puppy School", type="urn:entity:tv_show",
            found_in=place, verdict=VERDICTS[PUPPY_SCHOOL],
        ),
        DOG_SHOW: Entity(id=DOG_SHOW, name="Example Dog Show", type="urn:entity:tv_show"),
    }  # fmt: skip
    plan = ProfilePlan(titles=[{"entity_id": DOG_SHOW, "why": "dogs"}], venues=[])
    try:
        check_plan(SimpleNamespace(deps=d), plan)
    except Exception as exc:  # ModelRetry
        assert "keep the ones Qloo backs, such as Example Puppy School" in str(exc)
    else:
        raise AssertionError("check_plan accepted a plan with none of Qloo's titles")


def test_an_ais_title_kept_for_its_place_in_a_list_says_so_on_its_badge():
    from app.profile import LocationProfile

    place = FoundIn(signal="Example Dog Show", kind="tv_show", position=2, out_of=20)
    cat = Entity(id=CAT_SHOW, name="Example Cat Show", type="urn:entity:tv_show", listed_in=place)
    profile = LocationProfile(location_id=LOCATION.id, pet_entities=[cat])
    assert name_badge("pet", CAT_SHOW, profile) == (
        "Pet-themed title, liked here by fans of Example Dog Show"
    )


def test_venues_are_never_asked_for_unbacked_titles_while_backed_ones_exist():
    from app.agent.profile_agent import find_venues

    # Flash, PR #20: the AI sent only its own titles, and the venues and map rested on them.
    d = deps({pet_key("tv_show"): envelope("recommend", results=PET_LIST[:1])},
             FakeClassifier(VERDICTS))  # fmt: skip
    pet_lists(d)
    d.titles_seen[DOG_SHOW] = Entity(
        id=DOG_SHOW, name="Example Dog Show", type="urn:entity:tv_show"
    )
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    assert "send titles Qloo backs, such as Example Puppy School" in out["status"]
    assert d.venue_signals is None


def test_a_list_qloo_answered_without_the_tags_is_not_a_pet_list():
    listing = envelope(
        "recommend", results=PET_LIST, interpretation={"signal_location": LOCATION.query}
    )
    d = deps({pet_key("tv_show"): listing}, FakeClassifier(VERDICTS))
    assert pet_lists(d)["tv_show"]["status"] == "unavailable: Qloo did not take the pet tags"
    assert PUPPY_SCHOOL not in d.titles_seen


def test_the_four_pet_tags_are_the_ones_milestone_1_found():
    assert PET_TAGS == [
        "urn:tag:genre:media:dogs",
        "urn:tag:keyword:media:pet_dogs",
        "urn:tag:subgenre:qloo:pets",
        "urn:tag:keyword:qloo:cats",
    ]


def test_who_chose_credits_the_classifier_only_when_it_ran():
    from app.profile import LocationProfile

    place = FoundIn(signal="Qloo's pet tags", kind="tv_show", position=1, out_of=3, by_tags=True)
    puppy = Entity(id=PUPPY_SCHOOL, name="Puppy", type="urn:entity:tv_show", found_in=place)
    profile = LocationProfile(location_id=LOCATION.id, pet_entities=[puppy], made_by="agent")
    assert "classifier" not in who_chose(profile)
    profile.pet_entities[0].verdict = VERDICTS[PUPPY_SCHOOL]
    assert "and a classifier sorted them" in who_chose(profile)
