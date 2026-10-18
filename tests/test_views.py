import re

import pytest

from app.locations import load_locations
from app.profile import LocationProfile, Venue, build_profile, rank_band
from app.views.build import (
    FEATURED,
    RANK_NOTES,
    build_result_view,
    build_start_view,
    for_children,
    map_view,
    result_id,
    sentences,
    skipped_shown,
    why,
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
    # The community-channel suggestion is gone (decided 18 October): no source on the page.
    assert bases.count("Qloo") == 1 and "Our suggestion" not in bases
    assert not any("language" in item.text for item in view.plan)
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


def kids_profile() -> LocationProfile:
    p = profile()
    for v in p.venues:
        if v.name == "Garden Cafe":
            v.description = "A cafe with a garden and a kids' playground."
    return p


def with_children(roster, answer):
    animal = roster.get("dog-02")
    return animal.model_copy(
        update={"checks": animal.checks.model_copy(update={"good_with_children": answer})}
    )


def test_an_animal_not_good_with_children_skips_places_that_mention_them(roster):
    view = build_result_view(with_children(roster, "no"), LOCATION, kids_profile())
    assert "Garden Cafe" not in [v.name for v in view.venues]
    skip = [i for i in view.plan if i.text.startswith("Skip")]
    assert [i.text for i in skip] == [
        "Skip Garden Cafe (it mentions “kids”) for this dog: the record says she is not "
        "good with children."
    ]
    assert skip[0].basis == "Our suggestion"
    asks = next(i.text for i in view.plan if i.text.startswith("Ask"))
    assert "Garden Cafe" not in asks
    # Our reading says why; Qloo's column is untouched.
    reading = {i.title: i.detail for i in view.our_reading}
    assert reading["Skipped for this dog"].startswith(
        "Garden Cafe: its name or Qloo description mentions “kids”."
    )


def test_unknown_or_yes_keeps_every_venue(roster):
    for answer in ("unknown", "yes"):
        view = build_result_view(with_children(roster, answer), LOCATION, kids_profile())
        assert "Garden Cafe" in [v.name for v in view.venues]
        assert not any(i.text.startswith("Skip") for i in view.plan)


def test_the_children_words_match_whole_words_in_the_name_or_description():
    assert for_children(None, "A children's museum.") == "children"
    assert for_children("Childrens Museum of the Arts") == "childrens"
    assert for_children(None, "A child-friendly play cafe.") == "child"
    assert for_children(None, "Kid’s birthday parties.") == "kid"
    assert for_children(None, "Toddler classes and a playground.") == "toddler"
    assert for_children(None, "A family-friendly brewery.") == "family-friendly"
    assert for_children(None, "A soft play centre.") == "soft play"
    assert for_children(None, "Classes for babies and an elementary school club.") == "babies"
    # Other common meanings in venue text are not about children.
    for text in (
        "A plant nursery.",
        "A dog daycare.",
        "A restaurant serving baby back ribs.",
        "A youth hostel.",
        "A fenced play area for dogs.",
        "An off-leash play space for dogs.",
        "A bar for kidney-shaped pools.",
        None,
    ):
        assert for_children(None, text) is None, text


def test_when_every_venue_mentions_children_the_page_says_so(roster):
    p = kids_profile()
    for v in p.venues:
        v.description = "A cafe for kids."
    view = build_result_view(with_children(roster, "no"), LOCATION, p)
    assert view.venues == []
    assert view.venues_empty == (
        "Every place Namesake would suggest here mentions children, so none is suggested "
        "for this dog."
    )
    skip = next(i.text for i in view.plan if i.text.startswith("Skip"))
    assert skip.count("(it mentions “kids”)") == 3
    reading = {i.title: i.detail for i in view.our_reading}
    assert reading["Skipped for this dog"].count("mentions “kids”") == 3


def test_an_empty_profile_still_says_no_venues(roster):
    p = profile()
    p.venues = []
    view = build_result_view(with_children(roster, "no"), LOCATION, p)
    assert view.venues_empty == "No venues for this area yet."


def test_a_skipped_venue_is_named_whenever_a_lower_one_takes_its_slot():
    # Flash, PR #19: a fixed window of the first five missed a skipped venue that a
    # lower one replaced.
    every = [Venue(entity_id=str(n), name=f"Place {n}", rank=n + 1) for n in range(8)]
    skipped = [every[0], every[5]]
    kept = [v for v in every if v not in skipped]
    # Five shown: 1, 2, 3, 4, 6; places 0 and 5 both rank above place 6.
    assert [v.name for v in skipped_shown(every, kept, skipped)] == ["Place 0", "Place 5"]


def test_a_skipped_last_pick_of_three_is_still_named():
    # Codex and Flash, PR #19 re-check: an agent profile has at most three venues, and a
    # skipped lowest one vanished without a word.
    every = [Venue(entity_id=str(n), name=f"Place {n}", rank=n + 1) for n in range(3)]
    assert [v.name for v in skipped_shown(every, every[:2], every[2:])] == ["Place 2"]


def test_the_why_item_says_slots_were_taken_only_when_a_lower_place_moved_up(roster):
    # Codex, PR #19: skipping the last of three moves nothing up.
    p = kids_profile()
    view = build_result_view(with_children(roster, "no"), LOCATION, p)
    reading = {i.title: i.detail for i in view.our_reading}
    assert reading["Skipped for this dog"].endswith("is not good with children.")


def test_the_why_panels_venue_line_names_only_the_titles_searched(roster):
    # Hoboken, 18 October: the line named seven pet titles; the venues were asked for three.
    returned, _ = why(LOCATION, agent_profile())
    line = next(i for i in returned if i.title.endswith(f"places near {LOCATION.label}"))
    assert line.detail.startswith("Ranked for people who like Example Cat Show")
    assert "Example Dog Show" not in line.detail


def test_the_page_names_a_kind_even_for_qloos_generic_type():
    from app.profile import Entity, FoundIn
    from app.views.build import kind_word

    # Profiles saved before entity_type: where the title was found, else a TV show.
    found = FoundIn(signal="Example Dog Show", kind="movie", position=3, out_of=20)
    assert kind_word(Entity(id="x", name="x", type="urn:entity", found_in=found)) == "film"
    assert kind_word(Entity(id="x", name="x", type="urn:entity")) == "TV show"
    assert kind_word(Entity(id="x", name="x", type="urn:entity"), default=None) == "title"
    assert kind_word(Entity(id="x", name="x", type="movie")) == "film"  # a bare kind
    assert kind_word(Entity(id="x", name="x", type="urn:entity:book")) == "book"


def test_the_venue_line_falls_back_to_every_title_only_for_old_profiles():
    from app.views.build import venue_titles

    p = profile()
    p.venue_signals = []
    assert venue_titles(p) == "Example Dog Show and Example Cat Show"
    p.venue_signals = [p.pet_entities[1].id]
    assert venue_titles(p) == "Example Cat Show"


def test_the_venue_line_never_reads_empty():
    from app.views.build import venue_titles

    p = profile()
    p.venue_signals = ["00000000-0000-4000-8000-000000000999"]  # not among the titles
    # Codex, PR #17: never name other titles as the ones searched.
    assert venue_titles(p) == "the pet-themed titles searched"


def test_a_thin_map_says_so_on_the_page():
    # Flash, PR #13: a typed area passes on its own top show; its pet titles may still map
    # thinly, and the page must say so, not only when there are no cells.
    p = profile()
    p.cells = p.cells[:2]
    assert map_view(LOCATION, p).legend.startswith(
        f"Only 2 map cells here: Qloo's data for fans of pet-themed titles around "
        f"{LOCATION.label} is thin"
    )


def test_the_qloo_part_counts_what_qloo_returned_apart_from_the_ais_part(roster):
    p = agent_profile()  # ranked by Qloo; venues asked for the cat show; one picked
    p.order_source = "qloo_rank"
    part = build_result_view(roster.get("dog-02"), LOCATION, p).qloo_part
    assert part.qloo == (
        f"2 titles with Qloo's evidence for {LOCATION.label} (2 ranked here); "
        f"{len(p.venues)} places near the shelter, ranked for fans of Example Cat Show; "
        f"{len(p.cells)} map cell{'s' if len(p.cells) != 1 else ''} from its heatmaps."
    )
    # Semicolons keep the AI's acts apart from what Qloo did.
    assert part.ai == (
        "Proposed 2 titles for Qloo to check; picked 1 of the places to ask. "
        "The names and bio are the fixed template."
    )


def test_the_qloo_part_names_the_ais_order_and_titles_found_in_lists(roster):
    from app.profile import FoundIn

    p = agent_profile()
    p.order_source, p.ranked = "agent", []
    p.pet_entities[0].found_in = FoundIn(signal="x", kind="tv_show", position=2, out_of=20)
    part = build_result_view(roster.get("dog-02"), LOCATION, p).qloo_part
    assert part.qloo.startswith(
        f"1 title with Qloo's evidence for {LOCATION.label} (1 only in its lists"
    )
    assert part.ai == (
        "Proposed 1 title for Qloo to check; judged 1 unclear title; picked 1 of the places "
        "to ask; set the order, as Qloo's ranking was unavailable. The names and bio are the "
        "fixed template."
    )


def test_the_qloo_part_for_a_fixed_lookup_says_the_ai_was_not_used(roster):
    part = build_result_view(roster.get("dog-02"), LOCATION, profile()).qloo_part
    assert part.ai == (
        "Not used here: the titles are a fixed lookup, and the names and bio a fixed template."
    )


def test_the_qloo_part_says_plainly_when_nothing_came_back(roster):
    p = LocationProfile(location_id=LOCATION.id)
    part = build_result_view(roster.get("dog-02"), LOCATION, p).qloo_part
    assert part.qloo == f"Nothing for {LOCATION.label} yet."
    assert part.ai.startswith("Not used here")


def test_an_agent_profile_with_nothing_else_to_say_still_credits_the_ai(roster):
    from app.profile import FoundIn, PetVerdict

    p = agent_profile()
    p.order_source = "qloo_rank"
    kept = PetVerdict(pets=0.97, dogs=0.9, cats=0.1, family=0.9, real_people=0.05)
    for e in p.pet_entities:
        e.found_in = FoundIn(signal="x", kind="tv_show", position=1, out_of=20)
        e.verdict = kept
    for v in p.venues:
        v.chosen_reason = None
    part = build_result_view(roster.get("dog-02"), LOCATION, p).qloo_part
    assert part.ai == "Kept the titles above; the names and bio are the fixed template."


def test_a_title_both_ranked_and_listed_is_counted_once(roster):
    from app.profile import FoundIn

    p = agent_profile()  # both ranked
    p.pet_entities[0].found_in = FoundIn(signal="x", kind="tv_show", position=2, out_of=20)
    part = build_result_view(roster.get("dog-02"), LOCATION, p).qloo_part
    assert part.qloo.startswith(
        f"2 titles with Qloo's evidence for {LOCATION.label} (2 ranked here);"
    )


def test_a_fixed_lookup_with_a_saved_listing_says_both(roster):
    from tests.test_product import saved_listing

    part = build_result_view(roster.get("dog-02"), LOCATION, profile(), saved_listing()).qloo_part
    assert part.ai == (
        "Chose the names and wrote the bio from the shelter's records. The titles are a fixed "
        "lookup."
    )


def map_with(scores: list[tuple[float, float | None]]) -> LocationProfile:
    """A profile whose cells have these (pet, baseline) scores; None is a grey cell."""
    shaped = profile().model_copy(deep=True)
    first = shaped.cells[0]
    shaped.cells = [
        first.model_copy(
            update={"geohash": first.geohash[:-1] + "0123456789bcdefg"[i],
                    "pet_score": pet, "baseline_score": base}
        )
        for i, (pet, base) in enumerate(scores)
    ]  # fmt: skip
    return shaped


def test_the_map_caption_counts_the_warm_cells():
    # Decided 18 October: a mostly cool map says how many cells are warm, as coloured.
    view = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.5, 0.9), (0.4, 0.8), (0.3, 0.7), (0.2, 0.6)])
    )
    assert view.legend.startswith(
        "Fans of Example Dog Show and Example Cat Show stand out against fans of this area's "
        "top shows in 1 of these 5 cells. "
    )


def test_a_tie_is_cool_in_the_count_and_the_key():
    view = map_with([(0.5, 0.5), (0.9, 0.5), (0.5, 0.9), (0.4, 0.8), (0.3, 0.7)])
    legend = map_view(LOCATION, view).legend
    assert "in 1 of these 5 cells. " in legend and "Cool cells: lower, or level." in legend


def test_grey_cells_are_left_out_of_the_count():
    legend = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.8, None), (0.5, 0.9), (0.4, 0.8), (0.3, 0.7)])
    ).legend
    assert "in 1 of the 4 cells with a comparison. " in legend


def test_no_warm_cell_says_so():
    legend = map_view(
        LOCATION, map_with([(0.5, 0.9), (0.4, 0.8), (0.3, 0.7), (0.2, 0.6), (0.1, 0.5)])
    ).legend
    assert (
        "do not stand out against fans of this area's top shows in any of these cells. " in legend
    )


def test_one_compared_cell_among_grey_ones_reads_in_the_singular():
    legend = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.8, None), (0.7, None), (0.6, None), (0.5, None)])
    ).legend
    assert "in the one cell with a comparison. " in legend


def test_one_compared_cell_that_is_cool_says_so():
    legend = map_view(
        LOCATION, map_with([(0.5, 0.5), (0.8, None), (0.7, None), (0.6, None), (0.5, None)])
    ).legend
    assert "do not stand out against fans of this area's top shows in the one cell with" in legend


def test_every_cell_warm_says_all_these():
    legend = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.8, 0.4), (0.7, 0.3), (0.6, 0.2), (0.5, 0.1)])
    ).legend
    assert "in all 5 cells. " in legend


def test_an_all_grey_map_gets_no_count():
    legend = map_view(LOCATION, map_with([(0.9, None)] * 5)).legend
    assert "stand out against" not in legend and "no comparison here" in legend


def test_every_compared_cell_warm_says_all():
    legend = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.8, 0.4), (0.7, 0.3), (0.6, 0.2), (0.5, None)])
    ).legend
    assert "in all 4 cells with a comparison. " in legend


def test_a_thin_map_gets_no_count():
    # Fewer than five cells: the thin note says the map says little, so no count.
    legend = map_view(LOCATION, profile()).legend
    assert legend.startswith("Only 2 map cells here") and "stand out against" not in legend


def test_each_version_button_shows_its_name(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    generic, local = view.listing.versions
    assert generic.choice == f"Generic · {generic.name}"
    assert local.choice == "Local, with Qloo"  # no draft, so no local name


def test_the_left_out_note_says_the_backstory_stays_out(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    assert "Backstory and time in the shelter stay out of the listing." in view.listing.left_out


def test_a_venue_that_stands_out_says_so_in_plain_words(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    standing = [v for v in view.venues if v.stands_out]
    assert standing and all(v.badge == "Stands out for fans of pet-themed titles" for v in standing)
