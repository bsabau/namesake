import re

import pytest

from app.locations import load_locations
from app.profile import LocationProfile, build_profile, rank_band
from app.views.build import (
    FEATURED,
    RANK_NOTES,
    build_result_view,
    build_start_view,
    result_id,
    sentences,
)
from tests.qloo_fakes import (
    BASELINE,
    BASELINE_2,
    LOCATION,
    SEEDS,
    FakeQloo,
    envelope,
    key,
    standard_script,
)


def profile() -> LocationProfile:
    return build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)


def test_start_view_leads_with_the_featured_animal(roster):
    from app.config import get_settings

    locations = load_locations(get_settings().locations_file)
    view = build_start_view(roster, locations, locations[1].id)
    assert view.animals[0].id == FEATURED
    assert [loc.selected for loc in view.locations] == [False, True, False]
    assert "long stay" in view.animals[0].badges


def test_result_venues_put_distinctive_suitable_places_first(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    names = [v.name for v in view.venues]
    assert "Hookah Corner" not in names
    assert names[:2] == ["Community Hall", "Garden Cafe"]
    assert view.venues[0].stands_out and not view.venues[-1].stands_out
    # The baseline's own count, not the pet list's.
    assert "not among the 2 places for fans of this area's top shows" in view.venues[0].evidence


def test_plan_separates_research_qloo_and_our_suggestions(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    bases = [item.basis for item in view.plan]
    assert bases.count("Qloo") == 1 and bases[-1] == "Our suggestion"
    assert any("rescue partners" in item.text for item in view.plan)
    cat = build_result_view(roster.get("cat-01"), LOCATION, profile())
    assert not any("rescue partners" in item.text for item in cat.plan)
    assert view.plan_heading == "Get her seen"


def test_provenance_is_split(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    returned = " ".join(i.title + i.detail for i in view.qloo_returned)
    reading = " ".join(i.title + i.detail for i in view.our_reading)
    assert "Qloo has 2 entries" in returned and "qloo where_popular" in returned
    assert "Hookah Corner" in reading and "Lift on the map" in reading
    assert "Lift on the map" not in returned


def test_listing_view_lists_what_was_left_out(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    assert view.listing.left_out[0].startswith("Not yet known, so not mentioned")
    assert "eight months" not in view.listing.text
    assert view.name.value is None


def test_map_cells_carry_bounds_and_labels(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    cell = next(c for c in view.map.cells if c.lift is not None)
    assert cell.south < cell.north and cell.west < cell.east
    assert "Example Dog Show" in cell.label


def test_empty_profile_still_renders_a_result(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, LocationProfile(location_id="x"))
    assert view.venues == [] and view.map.empty_message
    assert not any(item.basis == "Qloo" for item in view.plan)


def test_result_id():
    assert result_id("dog-02", "park-slope") == "dog-02@park-slope"


def test_sentences_trims_at_a_sentence_end():
    assert sentences("One. Two is cut mid-wo") == "One."
    assert sentences(None) == ""


def baseline_key():
    return key(
        "recommend",
        {
            "target_type": "place",
            "signals": [BASELINE, BASELINE_2],
            "filter_location": LOCATION.query,
            "limit": 15,
        },
    )


def test_without_a_baseline_venues_say_not_compared(roster):
    script = standard_script()
    del script[baseline_key()]
    view = build_result_view(
        roster.get("dog-02"), LOCATION, build_profile(FakeQloo(script), LOCATION, SEEDS)
    )
    assert {v.badge for v in view.venues} == {"Not compared"}
    assert not any(v.stands_out for v in view.venues)
    assert all("not compared with a baseline" in v.evidence for v in view.venues)


@pytest.mark.parametrize("status", ["partial", "degraded"])
def test_an_incomplete_baseline_is_not_used_for_comparison(roster, status):
    script = standard_script()
    script[baseline_key()] = envelope(
        "recommend", status, results=script[baseline_key()].results, warnings=["thin"]
    )
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert not any(v.distinctive for v in p.venues)
    assert p.baseline_venue_count is None
    assert any(f"was {status}" in n for n in p.notes)


def test_short_listings_say_so_instead_of_padding(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    assert view.listing.word_count < 75
    assert view.listing.short_note and "only a few facts" in view.listing.short_note


def test_locations_carry_the_shelter_radius(roster):
    from app.config import get_settings

    locations = load_locations(get_settings().locations_file)
    view = build_start_view(roster, locations, locations[0].id)
    by_id = {loc.id: loc for loc in view.locations}
    assert by_id["park-slope"].shelter_radius_m == 800
    assert by_id["austin"].shelter_radius_m == 6400


def agent_profile():
    p = profile()
    p.made_by = "agent"
    p.venue_signals = [p.pet_entities[1].id]  # the venues were asked for the cat show only
    p.ranked = [p.pet_entities[1].id, p.pet_entities[0].id]
    for v in p.venues:
        v.chosen_reason = "a community arts centre" if v.name == "Community Hall" else None
    return p


def test_an_agent_profile_suggests_only_the_agents_picks(roster):
    # Regression (Codex, milestone 3): unpicked venues reached the plan.
    view = build_result_view(roster.get("dog-02"), LOCATION, agent_profile())
    assert [v.name for v in view.venues] == ["Community Hall"]
    assert view.venues[0].reason == "a community arts centre"
    qloo_items = [i.text for i in view.plan if i.basis == "Qloo"]
    assert qloo_items == ["Ask Community Hall about hosting an adoption event or a flyer."]


def test_venue_evidence_names_only_the_titles_searched(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, agent_profile())
    assert "for fans of Example Cat Show;" in view.venues[0].evidence
    assert "Example Dog Show" not in view.venues[0].evidence


def test_a_pet_name_claims_local_strength_only_when_qloo_ranked_it():
    from app.views.build import name_badge

    p = agent_profile()
    cat, dog = p.pet_entities[1].id, p.pet_entities[0].id
    assert name_badge("pet", cat, p) == "Pet-themed title, ranked 1st of 2 here by Qloo"
    p.ranked = []
    assert name_badge("pet", dog, p) == "Pet-themed title"
    assert name_badge("local", dog, p) == "Watched locally"


def test_rank_band_splits_qloos_list_in_thirds():
    assert [rank_band(r, 15) for r in (1, 5, 6, 10, 11, 15)] == [
        "top",
        "top",
        "middle",
        "middle",
        "bottom",
        "bottom",
    ]
    assert rank_band(1, 1) == "top"
    assert [rank_band(r, 2) for r in (1, 2)] == ["top", "bottom"]


def test_venue_rank_is_stated_plainly(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    total = len(profile().venues)
    for v in view.venues:
        assert re.fullmatch(rf"\d+(st|nd|rd|th) of {total}", v.rank)
        assert v.rank_note == RANK_NOTES[v.rank_band]


def test_a_thin_map_says_so_on_the_page():
    # Flash, PR #13: a typed area passes on its own top show; its pet titles may still map
    # thinly, and the page must say so, not only when there are no cells.
    from app.views.build import map_view

    p = profile()
    p.cells = p.cells[:2]
    assert map_view(LOCATION, p).legend.startswith(
        f"Only 2 map cells here: Qloo's data for pet-show fans around {LOCATION.label} is thin"
    )
