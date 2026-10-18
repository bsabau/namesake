"""Venues asked within kinds of place that can host an adoption stand (decided 18 October)."""

from types import SimpleNamespace

from app.agent.profile_agent import ProfileDeps, find_venues
from app.agent.steps import StepLog
from app.profile import (
    CATEGORY_TAGS,
    LEFT_OUT_GROUPS,
    MIN_CATEGORY_VENUES,
    VENUE_GROUPS,
    Entity,
    LocationProfile,
    build_profile,
    finish_profile,
    venue_input,
)
from app.views.build import kinds_reading, venues_note
from tests.qloo_fakes import (
    BASELINE,
    BASELINE_2,
    CAT_SHOW,
    DOG_SHOW,
    LOCATION,
    PET_VENUES,
    SEEDS,
    FakeQloo,
    envelope,
    key,
    standard_script,
    venue,
)

# Cafes and shops, more than MIN_CATEGORY_VENUES of them.
CAFES = [
    venue(10 + n, f"Example Cafe {n}", "A neighbourhood cafe.", {DOG_SHOW: 1.0}) for n in range(6)
]


def filtered_script(base_results: list[dict], pet_results: list[dict] = CAFES) -> dict:
    """The standard profile, with the category-filtered questions answered on their own."""
    script = standard_script()
    for signals, results in (
        ([BASELINE, BASELINE_2], base_results),
        ([DOG_SHOW, CAT_SHOW], pet_results),
        ([CAT_SHOW, DOG_SHOW], pet_results),
    ):
        script[key("recommend", venue_input(signals, LOCATION, True))] = envelope(
            "recommend", results=results
        )
    return script


def test_the_request_asks_within_at_most_ten_categories():
    assert len(CATEGORY_TAGS) == len(set(CATEGORY_TAGS)) <= 10
    assert all(t.startswith("urn:tag:category:place:") for t in CATEGORY_TAGS)
    plain = venue_input([DOG_SHOW], LOCATION, False)
    assert "include_tags" not in plain
    asked = venue_input([DOG_SHOW], LOCATION, True)
    assert asked == plain | {"include_tags": CATEGORY_TAGS, "include_tags_operator": "union"}
    # Every group says why it is in, and every left-out group why it is out.
    assert all(why for _, _, why in VENUE_GROUPS) and all(why for _, why in LEFT_OUT_GROUPS)


def test_an_area_with_enough_such_places_asks_both_lists_within_them():
    qloo = FakeQloo(filtered_script(CAFES))
    profile = build_profile(qloo, LOCATION.model_copy(), SEEDS)
    assert profile.venue_categories is True
    asked = [i for op, i in qloo.calls if op == "recommend" and i["target_type"] == "place"]
    assert asked and all(i.get("include_tags") == CATEGORY_TAGS for i in asked)
    assert [v.name for v in profile.venues][:2] == ["Example Cafe 0", "Example Cafe 1"]
    # The comparison was asked the same way: every cafe is in both lists, none stands out.
    assert all(v.compared and not v.distinctive for v in profile.venues)


def test_an_area_with_too_few_such_places_uses_every_place_for_both_lists():
    few = CAFES[: MIN_CATEGORY_VENUES - 1]
    qloo = FakeQloo(filtered_script(few))
    profile = build_profile(qloo, LOCATION.model_copy(), SEEDS)
    assert profile.venue_categories is False
    pet_asks = [i for op, i in qloo.calls if op == "recommend" and DOG_SHOW in i.get("signals", [])]
    assert pet_asks and all("include_tags" not in i for i in pet_asks)
    assert [v.name for v in profile.venues] == [v["name"] for v in PET_VENUES]


def deps(script: dict, venue_filter=None) -> ProfileDeps:
    d = ProfileDeps(
        qloo=FakeQloo(script),
        location=LOCATION,
        species="dog",
        log=StepLog(),
        venue_filter=venue_filter,
    )
    d.titles_seen[DOG_SHOW] = Entity(
        id=DOG_SHOW, name="Example Dog Show", type="urn:entity:tv_show"
    )
    return d


def answered(results: list[dict], filtered: bool) -> dict:
    return {
        key("recommend", venue_input([DOG_SHOW], LOCATION, filtered)): envelope(
            "recommend", results=results
        )
    }


def test_find_venues_asks_as_the_comparison_decided():
    d = deps(answered(CAFES, True) | answered(PET_VENUES, False), venue_filter=False)
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    assert out["status"] == "found" and d.venue_filter is False
    assert all("include_tags" not in i for _, i in d.qloo.calls)


def test_find_venues_without_a_comparison_falls_back_when_few_such_places():
    d = deps(answered(CAFES[:2], True) | answered(PET_VENUES, False))
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    assert d.venue_filter is False and len(out["venues"]) == len(PET_VENUES)
    d = deps(answered(CAFES, True))
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    assert d.venue_filter is True and len(out["venues"]) == len(CAFES)


def test_finishing_a_profile_asks_its_venues_as_they_were_asked():
    # A profile saved before the categories keeps every place, so the AI's picks still match.
    old = build_profile(FakeQloo(standard_script()), LOCATION.model_copy(), SEEDS)
    old.venue_categories = None
    qloo = FakeQloo(filtered_script(CAFES))
    new = finish_profile(old, LOCATION.model_copy(), qloo, SEEDS)
    assert new is not None and new.venue_categories is None
    assert all("include_tags" not in i for op, i in qloo.calls if op == "recommend")


def profile_with(categories) -> LocationProfile:
    p = build_profile(FakeQloo(standard_script()), LOCATION.model_copy(), SEEDS)
    p.venue_categories = categories
    return p


def test_the_note_says_which_kinds_are_in_and_out_and_that_the_places_are_the_areas():
    note = venues_note(profile_with(True), "dog")
    for name, _, why in VENUE_GROUPS:
        assert f"{name} ({why})" in note
    for name, why in LEFT_OUT_GROUPS:
        assert f"{name} ({why})" in note
    assert "The same places for every dog at this shelter" in note
    assert venues_note(profile_with(False), "cat").startswith(
        "Qloo's list here, asked for the usual kinds"
    )
    assert venues_note(profile_with(None), "dog").endswith(
        "the name and the listing are this animal's."
    )
    assert venues_note(LocationProfile(location_id="x"), "dog") is None


def test_the_why_panel_reads_the_kinds_as_namesakes_choice():
    reading = kinds_reading(profile_with(True))
    assert reading.startswith("Namesake asked Qloo for these kinds only")
    assert "Namesake's AI judge each" in reading
    assert "asked for places of any kind" in kinds_reading(profile_with(False))


def plain_script(base_filtered, pet_filtered=None) -> dict:
    """The standard profile with its own answers to the filtered questions (None: a miss)."""
    script = standard_script()
    for signals, answer in (
        ([BASELINE, BASELINE_2], base_filtered),
        ([DOG_SHOW, CAT_SHOW], pet_filtered),
        ([CAT_SHOW, DOG_SHOW], pet_filtered),
    ):
        if answer is not None:
            script[key("recommend", venue_input(signals, LOCATION, True))] = answer
    return script


def test_an_empty_full_answer_falls_back_and_the_area_still_gets_places():
    # Reviewers, PR #32: an empty answer was read as a failure, leaving no venues at all.
    qloo = FakeQloo(plain_script(envelope("recommend", "empty", results=[])), twins=False)
    profile = build_profile(qloo, LOCATION.model_copy(), SEEDS)
    assert profile.venue_categories is False
    assert [v.name for v in profile.venues] == [v["name"] for v in PET_VENUES]


def test_a_failed_or_partial_comparison_decides_nothing():
    # The pet titles' full answer decides instead: here enough such places.
    for failed in (None, envelope("recommend", "partial", results=CAFES[:2])):
        qloo = FakeQloo(plain_script(failed, envelope("recommend", results=CAFES)), twins=False)
        profile = build_profile(qloo, LOCATION.model_copy(), SEEDS)
        assert profile.venue_categories is True
        assert [v.name for v in profile.venues][:1] == ["Example Cafe 0"]
        assert not any(v.compared for v in profile.venues)  # no comparison to claim


def test_a_failed_pet_question_never_flips_the_decision_or_asks_again():
    # No comparison, and the filtered pet question fails: no claim the area is thin.
    qloo = FakeQloo(plain_script(None), twins=False)
    profile = build_profile(qloo, LOCATION.model_copy(), SEEDS)
    assert profile.venue_categories is True and profile.venues == []
    pet_asks = [i for op, i in qloo.calls if op == "recommend" and DOG_SHOW in i.get("signals", [])]
    assert len(pet_asks) == 1 and "include_tags" in pet_asks[0]


def test_find_venues_is_not_flipped_by_an_ambiguous_or_partial_answer():
    for answer in (
        envelope("recommend", "needs_input", results=[]),
        envelope("recommend", "partial", results=CAFES[:2]),
    ):
        script = {key("recommend", venue_input([DOG_SHOW], LOCATION, True)): answer}
        d = deps(script)
        d.qloo = FakeQloo(script, twins=False)
        find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
        assert d.venue_filter is None and len(d.qloo.calls) == 1


def test_find_venues_keeps_the_categories_a_comparison_chose():
    d = deps(answered(CAFES, True), venue_filter=True)
    d.qloo = FakeQloo(answered(CAFES, True), twins=False)
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    assert len(out["venues"]) == len(CAFES) and d.venue_filter is True


def test_a_place_only_the_pet_list_has_still_stands_out_within_the_kinds():
    base = CAFES[1:] + [venue(30, "Example Library", "A public library.", {BASELINE: 1.0})]
    qloo = FakeQloo(filtered_script(base), twins=False)
    profile = build_profile(qloo, LOCATION.model_copy(), SEEDS)
    out = {v.name: v.distinctive for v in profile.venues}
    assert out["Example Cafe 0"] is True and out["Example Cafe 1"] is False


def test_finishing_a_categorised_profile_keeps_the_categories():
    old = build_profile(FakeQloo(filtered_script(CAFES)), LOCATION.model_copy(), SEEDS)
    assert old.venue_categories is True
    # Now thin within the kinds, but asked as before, so the AI's picks still match.
    script = filtered_script(CAFES[:2], pet_results=CAFES)
    qloo = FakeQloo(script, twins=False)
    new = finish_profile(old, LOCATION.model_copy(), qloo, SEEDS)
    assert new is not None and new.venue_categories is True
    asks = [i for op, i in qloo.calls if op == "recommend" and i["target_type"] == "place"]
    assert asks and all("include_tags" in i for i in asks)
    assert [v.name for v in new.venues][:1] == ["Example Cafe 0"]


def test_finishing_a_profile_whose_venues_never_arrived_records_the_new_decision():
    # Reviewers, PR #32: the old flag was written back over the fresh decision.
    for old_flag, base, expected in ((True, [], False), (False, CAFES, True)):
        old = build_profile(FakeQloo(filtered_script(CAFES)), LOCATION.model_copy(), SEEDS)
        old.venue_categories, old.venues = old_flag, []
        script = filtered_script(base)
        if not base:
            script[key("recommend", venue_input([BASELINE, BASELINE_2], LOCATION, True))] = (
                envelope("recommend", "empty", results=[])
            )
        new = finish_profile(old, LOCATION.model_copy(), FakeQloo(script, twins=False), SEEDS)
        assert new is not None and new.venue_categories is expected


def test_a_filtered_probe_that_falls_back_leaves_no_note():
    # Reviewers, PR #32: "Qloo returned no venues" stayed beside a compared list.
    script = standard_script()
    script[key("recommend", venue_input([BASELINE, BASELINE_2], LOCATION, True))] = envelope(
        "recommend", "empty", results=[]
    )
    profile = build_profile(FakeQloo(script, twins=False), LOCATION.model_copy(), SEEDS)
    assert profile.venue_categories is False and profile.venues[0].compared
    assert not any("returned no venues" in n for n in profile.notes)


def test_national_chains_are_named_by_the_start_of_their_name():
    from app.profile import chain_name, fast_food_mention

    for name in (
        "McDonald's",
        "McDonald\u2019s",
        "Starbucks Coffee Company",
        "Wendy\u2019s",
        "Dunkin'",
        "Joe & The Juice",
        "Mc Donald's",
    ):
        assert chain_name(name) == "a national chain", name
    # Independent places, pet-shop chains (they hold adoption events), everyday words, and
    # a chain's name inside another name pass.
    for name in ("BrownStone Bagels", "Petco", "PetSmart", "Target Practice Range",
                 "Subway Inn", "Joe's Starbucks Lane", "The Shake Shack Bakery Co"):  # fmt: skip
        assert chain_name(name) is None, name
    # Fast food is told to the AI, unless the description says the place is not.
    assert fast_food_mention("A fast-food burger counter.")
    assert fast_food_mention("Burgers at the drive-through.")
    for text in ("An alternative to fast food.", "A cafe with no drive-thru.", None):
        assert not fast_food_mention(text), text


def test_a_chain_pick_is_sent_back_and_the_tool_marks_it():
    from pydantic_ai import ModelRetry

    from app.agent.profile_agent import ProfilePlan, check_plan

    chain = venue(40, "McDonald's", "A fast-food restaurant.", {DOG_SHOW: 1.0})
    d = deps(answered([chain, *CAFES], True))
    out = find_venues(SimpleNamespace(deps=d), [DOG_SHOW])
    marked = {v["name"]: (v["chain"], v["fast_food"]) for v in out["venues"]}
    assert marked["McDonald's"] == ("a national chain", True)
    assert marked["Example Cafe 0"] == (None, False)
    plan = ProfilePlan(
        titles=[{"entity_id": DOG_SHOW, "why": "dogs"}],
        venues=[{"entity_id": chain["entity_id"], "reason": "It has room for a stand."}],
    )
    try:
        check_plan(SimpleNamespace(deps=d), plan)
        problems = ""
    except ModelRetry as retry:
        problems = str(retry)
    assert "McDonald's is a national chain" in problems


def test_the_note_says_what_the_chain_rule_enforces_on_every_profile():
    for categories in (True, False, None):
        note = venues_note(profile_with(categories), "dog")
        assert "National chains Namesake knows by name are left out" in note, categories


def test_a_chain_is_never_suggested_even_by_the_fixed_lookup():
    # Reviewers, PR #36: the fallback profile suggested a chain under the note.
    from app.views.build import venue_order, why

    profile = profile_with(True)
    profile.venues[0].name = "McDonald's"
    assert "McDonald's" not in [v.name for v in venue_order(profile)]
    _, reading = why(LOCATION, profile)
    assert any(i.title == "Left out as national chains" and "McDonald's" in i.detail
               for i in reading)  # fmt: skip


def test_the_fast_food_sentence_shows_only_where_the_ai_picked():
    seeds = profile_with(True)
    assert "fast food" not in venues_note(seeds, "dog")
    seeds.made_by = "agent"
    assert "Namesake's AI is asked to pass over fast food." in venues_note(seeds, "dog")


def test_an_area_of_only_chains_says_so(roster):
    from app.views.build import build_result_view

    profile = profile_with(True)
    for v in profile.venues:
        v.name, v.unsuitable = "Starbucks", None
    view = build_result_view(roster.get("dog-02"), LOCATION, profile)
    assert view.venues == [] and view.venues_empty.startswith("Every suitable place Qloo listed")


def test_a_mixed_list_with_no_pick_never_claims_every_place_is_a_chain():
    # Reviewers, PR #36: one chain made the page say every place was one.
    from app.views.build import empty_venues

    profile = profile_with(True)
    profile.made_by = "agent"
    for v in profile.venues:
        v.unsuitable, v.chosen_reason = None, None
    profile.venues[0].name = "Starbucks"
    assert empty_venues(profile).startswith("Namesake's AI found no place")
    for v in profile.venues:
        v.unsuitable = "a hookah lounge"
    assert empty_venues(profile).startswith("Every place Qloo listed here was screened out")
