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
        f"Qloo had fewer than {MIN_CATEGORY_VENUES} cafes, shops or community places"
    )
    assert venues_note(profile_with(None), "dog").startswith("The same places for every dog")
    assert venues_note(LocationProfile(location_id="x"), "dog") is None


def test_the_why_panel_reads_the_kinds_as_namesakes_choice():
    reading = kinds_reading(profile_with(True))
    assert reading.startswith("Namesake asked Qloo for these kinds only")
    assert "Namesake's AI judge each" in reading
    assert "every place it ranks was used" in kinds_reading(profile_with(False))
