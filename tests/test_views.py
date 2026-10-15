from app.locations import load_locations
from app.profile import LocationProfile, build_profile
from app.views.build import (
    FEATURED,
    build_result_view,
    build_start_view,
    result_id,
    sentences,
)
from tests.qloo_fakes import LOCATION, SEEDS, FakeQloo, standard_script


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
    assert "not among the top" in view.venues[0].evidence


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
