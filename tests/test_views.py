import pathlib
import re

import pytest
from pydantic import SecretStr

from app.locations import load_locations
from app.profile import LocationProfile, Venue, build_profile, rank_band
from app.views.build import (
    FEATURED,
    RANK_NOTES,
    build_result_view,
    build_start_view,
    for_children,
    local_touch,
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
    assert [loc.selected for loc in view.locations] == [False, True, False, False]
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
    # Qloo's place, the AI's pick: the pill says Qloo, the words say who picked it.
    assert qloo_items == [
        "Ask Community Hall (picked by Namesake's AI from Qloo's list) about hosting an "
        "adoption event or a flyer."
    ]


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
    # Spanish and Catalan venue names (Barcelona).
    assert for_children("Ludoteca Infantil El Drac") == "ludoteca"
    assert for_children("Espai per a nens i famílies") == "nens"
    assert for_children("Parque de niños") == "niños"
    assert for_children(None, "Un espai per a famílies.") == "famílies"
    assert for_children(None, "Un café para familias.") == "familias"
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
        f"2 titles with Qloo's evidence for {LOCATION.label} (2 in its ranking here); "
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
    # The search the AI chose comes first (Fable audit, 19 October: it was invisible).
    assert part.ai == (
        "Searched Qloo's lists with x; proposed 1 title for Qloo to check; judged 1 unclear "
        "title; picked 1 of the places to ask; set the order, as Qloo's ranking was "
        "unavailable. The names and bio are the fixed template."
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


def test_the_local_touch_names_only_what_came_from_qloo_here(roster):
    # Decision 33: one plain line under the names; each part rests on the area's data.
    from types import SimpleNamespace

    p = profile()
    p.ranked = [p.pet_entities[0].id]
    ranked, looked_up = p.pet_entities[0].id, p.pet_entities[1].id

    def drafted(*options):
        names = [SimpleNamespace(entity_id=i, source=s) for i, s in options]
        return SimpleNamespace(draft=SimpleNamespace(names=names))

    assert local_touch(LOCATION, p, drafted((ranked, "pet")), 3) == (
        f"From Qloo taste data for {LOCATION.label}: the titles behind the names, "
        "3 places to ask and the map."
    )
    # A title only looked up, or a lookalike, has no evidence for the area: not claimed.
    some = drafted((ranked, "pet"), (looked_up, "pet"), (ranked, "lookalike"))
    assert local_touch(LOCATION, p, some, 3).startswith(
        f"From Qloo taste data for {LOCATION.label}: the titles behind 1 of the 3 names, "
    )
    none = drafted((looked_up, "pet"), ("x", "lookalike"))
    assert "names" not in local_touch(LOCATION, p, none, 3)
    # The fixed template names nothing from Qloo; no places, no cells: nothing to claim.
    assert local_touch(LOCATION, p, None, 1) == (
        f"From Qloo taste data for {LOCATION.label}: 1 place to ask and the map."
    )
    empty = LocationProfile(location_id=LOCATION.id)
    assert local_touch(LOCATION, empty, None, 0) == ""
    # With a listing whose names have Qloo's evidence, only the local version's line
    # names them: the generic version's names are a fixed list.
    from tests.test_product import saved_listing

    agent = agent_profile()
    view = build_result_view(roster.get("dog-02"), LOCATION, agent, saved_listing())
    assert "the titles behind" in view.local_touch
    assert "names" not in view.local_touch_generic and view.local_touch_generic.endswith("map.")


def test_the_result_says_the_local_version_is_untested_and_how_to_test_it(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    assert view.trial.startswith("Does the local version help? Nobody has tested it yet.")
    assert view.trial_link.url.endswith("#measuring-whether-it-works")
    # Claims stay within the evidence: a trial size, never a promise of faster adoption.
    assert "would detect" not in view.trial and "detect a 50% faster rate" in view.trial


def test_the_start_page_states_the_problem_and_links_the_research(roster):
    from app.config import get_settings

    view = build_start_view(roster, load_locations(get_settings().locations_file), None)
    assert view.problem.startswith("Volunteers write a listing for every animal")
    assert view.problem_link.url.endswith("docs/research/adoption-evidence-review.md")


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
    assert part.ai == "Searched Qloo's lists with x. The names and bio are the fixed template."
    for e in p.pet_entities:
        e.found_in.by_tags = True  # Qloo's pet-tag lists are code's, not a search
    part = build_result_view(roster.get("dog-02"), LOCATION, p).qloo_part
    assert part.ai == "Kept the titles above; the names and bio are the fixed template."


def test_a_title_both_ranked_and_listed_is_counted_once(roster):
    from app.profile import FoundIn

    p = agent_profile()  # both ranked
    p.pet_entities[0].found_in = FoundIn(signal="x", kind="tv_show", position=2, out_of=20)
    part = build_result_view(roster.get("dog-02"), LOCATION, p).qloo_part
    assert part.qloo.startswith(
        f"2 titles with Qloo's evidence for {LOCATION.label} (2 in its ranking here);"
    )


def test_a_fixed_lookup_with_a_saved_listing_says_both(roster):
    from tests.test_product import saved_listing

    part = build_result_view(roster.get("dog-02"), LOCATION, profile(), saved_listing()).qloo_part
    assert part.ai == (
        "Chose the names and wrote the bio from the shelter's records. The titles are a fixed "
        "lookup."
    )


def map_with(scores: list[tuple[float, float | None]]) -> LocationProfile:
    """A profile whose cells have these (pet, baseline) scores; None is a grey cell. Built
    through validation, as a saved one loads, so the cells are on one scale (one_scale)."""
    shaped = profile().model_copy(deep=True)
    first = shaped.cells[0]
    shaped.cells = [
        first.model_copy(
            update={"geohash": first.geohash[:-1] + "0123456789bcdefg"[i],
                    "pet_score": pet, "baseline_score": base}
        )
        for i, (pet, base) in enumerate(scores)
    ]  # fmt: skip
    return LocationProfile.model_validate(shaped.model_dump())


def test_the_map_caption_counts_the_warm_cells_and_says_what_they_mean():
    # Decided 18 October: the caption counts the warm cells, as coloured. Since 22 October
    # both sides are ranked among the same cells, so it says that shows where, not how many.
    view = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.5, 0.9), (0.4, 0.8), (0.3, 0.7), (0.2, 0.6)])
    )
    assert view.legend.startswith(
        "Fans of Example Dog Show and Example Cat Show rank 1 of these 5 cells higher than "
        "fans of this area's top shows do. Both sides are ranked among the same cells, so "
        "this compares parts of "
    )
    assert "compares parts of Example Slope, not how many fans live there." in view.legend


def test_a_cell_label_gives_places_not_rescaled_scores():
    # Flash: the re-ranked numbers are Namesake's; a label showing them reads as Qloo's.
    view = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.5, 0.9), (0.4, 0.8), (0.3, 0.7), (0.2, 0.6)])
    )
    assert view.cells[0].label == (
        "Fans of Example Dog Show and Example Cat Show (2 shows): 1st of these 5 cells; "
        "fans of this area's top shows (2 shows): 5th."
    )


def test_tied_places_read_as_a_range_that_agrees_with_the_colour():
    # Codex: four cells tie on the pet side; the first is 2nd for the baseline. Its pet
    # place, 1st to 4th, centres below 2nd, as its cool colour says.
    view = map_view(
        LOCATION, map_with([(0.9, 0.8), (0.9, 0.9), (0.9, 0.7), (0.9, 0.6), (0.1, 0.1)])
    )
    first = view.cells[0]
    assert first.lift is not None and first.lift < 0
    assert "joint 1st to 4th of these 5 cells" in first.label and first.label.endswith(": 2nd.")


def test_a_tie_is_cool_in_the_count_and_the_key():
    view = map_with([(0.5, 0.5), (0.9, 0.5), (0.5, 0.9), (0.4, 0.8), (0.3, 0.7)])
    legend = map_view(LOCATION, view).legend
    assert "rank 2 of these 5 cells higher" in legend and "cool where lower, or level" in legend


def test_grey_cells_are_left_out_of_the_count():
    legend = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.8, None), (0.5, 0.9), (0.4, 0.8), (0.3, 0.7)])
    ).legend
    assert "rank 1 of the 4 cells with a comparison higher" in legend


def test_two_sides_that_order_the_cells_alike_say_so():
    legend = map_view(
        LOCATION, map_with([(0.5, 0.9), (0.4, 0.8), (0.3, 0.7), (0.2, 0.6), (0.1, 0.5)])
    ).legend
    assert (
        "Fans of Example Dog Show and Example Cat Show order these cells as fans of this "
        "area's top shows do. " in legend
    )
    # Review of PR #48: the colour key follows as a key, never as a second finding, and
    # the shelter's circle is explained.
    assert "Warm cells:" not in legend and "Colours: warm where" in legend
    note = map_view(
        LOCATION, map_with([(0.5, 0.9), (0.4, 0.8), (0.3, 0.7), (0.2, 0.6), (0.1, 0.5)])
    ).note
    assert note.endswith("Circle: around the sample shelter the animals are adopted from.")
    # Codex and flash: around a spot the visitor picked, the circle is not made up.
    picked = map_view(
        LOCATION,
        map_with([(0.5, 0.9), (0.4, 0.8), (0.3, 0.7), (0.2, 0.6), (0.1, 0.5)]),
        pin=(LOCATION.latitude, LOCATION.longitude),
    ).note
    assert picked.endswith("Circle: around the spot you picked for the shelter.")


def test_one_compared_cell_has_nothing_to_compare():
    view = map_view(
        LOCATION, map_with([(0.9, 0.5), (0.8, None), (0.7, None), (0.6, None), (0.5, None)])
    )
    assert "Only one cell was scored for both sides, so there is nothing to compare. " in (
        view.legend
    )
    assert view.cells[0].label.endswith("the only such cell, so nothing to compare it with.")


def test_an_all_grey_map_gets_no_count():
    legend = map_view(LOCATION, map_with([(0.9, None)] * 5)).legend
    assert "cells higher than" not in legend and "no comparison here" in legend


def test_a_thin_map_gets_no_count():
    # Fewer than five cells: the thin note says the map says little, so no count.
    legend = map_view(LOCATION, profile()).legend
    assert legend.startswith("Only 2 map cells here") and "cells higher than" not in legend


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


def test_map_tiles_are_carto_with_a_key_and_openstreetmap_without(monkeypatch):
    from app.config import get_settings
    from app.views.build import map_tiles

    monkeypatch.setattr(get_settings(), "map_tiles_key", SecretStr("test-key"))
    tiles = map_tiles()
    assert (
        tiles.url == "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?key=test-key"
    )
    assert (
        tiles.dark_url
        == "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=test-key"
    )
    assert tiles.subdomains == "abcd" and tiles.max_zoom == 20
    assert "openstreetmap.org/copyright" in tiles.attribution
    assert "carto.com/attributions" in tiles.attribution

    monkeypatch.setattr(get_settings(), "map_tiles_key", None)
    plain = map_tiles()
    assert plain.url == plain.dark_url == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    assert plain.subdomains == "" and plain.max_zoom == 19
    assert "CARTO" not in plain.attribution and "key" not in plain.url
    # A keyed basemap that keeps failing gives way to OpenStreetMap, named by the view model.
    assert tiles.fallback_url == plain.url and tiles.fallback_attribution == plain.attribution
    assert plain.fallback_url == ""


def test_every_map_carries_its_tiles(roster, monkeypatch):
    from app.config import get_settings

    locations = load_locations(get_settings().locations_file)
    monkeypatch.setattr(get_settings(), "map_tiles_key", SecretStr("test-key"))
    start = build_start_view(roster, locations, locations[0].id)
    result = build_result_view(roster.get("dog-02"), LOCATION, profile())
    assert "key=test-key" in start.map_tiles.url and "key=test-key" in result.map.tiles.url
    # Served as JSON too: the key is a public basemap key that reaches the browser.
    assert "test-key" in result.model_dump_json()
    # But never in a settings dump: it is a SecretStr like the other keys.
    assert "test-key" not in repr(get_settings())


def test_the_animal_card_lists_the_record_and_what_is_unknown(roster):
    from app.views.build import animal_card

    card = animal_card(roster.get("dog-02"))
    assert card.facts == ["Needs an owner comfortable with a big dog", "Knows basic commands"]
    assert card.unknown == ["children", "dogs", "cats", "house-training", "bite history"]
    card = animal_card(roster.get("cat-03"))
    assert card.facts[-2:] == ["Best without other dogs", "Best without cats"]
    assert "dogs" not in card.unknown and "children" in card.unknown
    card = animal_card(roster.get("dog-01"))
    assert card.facts == ["Good with children", "House-trained"]


def test_story_headings_use_the_animals_pronoun(roster):
    her = build_result_view(roster.get("dog-02"), LOCATION, profile())
    assert her.story_heading == "Let's tell her story."
    assert her.introduction_heading == "Her introduction"
    assert her.travel_heading == "Help her story travel"
    assert her.story_lead.endswith("A plan for getting her seen.")
    him = build_result_view(roster.get("dog-01"), LOCATION, profile())
    assert him.story_heading == "Let's tell his story."
    assert him.introduction_heading == "His introduction"


def test_the_confirmed_lines_cover_every_check():
    from app.listing import CHECK_SENTENCES
    from app.views.build import CONFIRMED_LINES

    assert set(CONFIRMED_LINES) == set(CHECK_SENTENCES)
    for field, lines in CONFIRMED_LINES.items():
        assert set(lines) == set(CHECK_SENTENCES[field]) == {"yes", "no"}


def test_a_check_the_lines_do_not_know_is_skipped_not_an_error(roster, monkeypatch):
    from app.views import build

    monkeypatch.setattr(build, "CONFIRMED_LINES", {})
    assert build.animal_card(roster.get("dog-01")).facts == []


def test_the_story_leads_are_true_of_each_version(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())  # no draft
    assert view.story_lead.startswith("No local name yet: it needs a run of Namesake's AI. ")
    assert view.story_lead_generic.startswith(
        "A common pet name from a fixed list, not from Qloo. "
    )
    assert view.story_lead.endswith("A plan for getting her seen.")
    assert view.story_lead_generic.endswith("A plan for getting her seen.")


def test_the_process_steps_say_what_happened_for_a_fixed_lookup(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    facts, context, interpret = view.process
    assert facts.title == "Start with the facts" and "fixed template" in facts.detail
    assert context.title == "Add local context"
    # The fixed lookup's fake profile has the area's watched list, places and cells but no
    # ranking: it says so.
    assert context.detail.startswith(
        f"Qloo returned its list of titles watched around {LOCATION.label}, 4 places near "
        "the shelter for fans of"
    )
    assert "map cells within" in context.detail
    assert context.detail.endswith("Its ranking of the titles was unavailable.")
    assert "ranking of" not in context.detail.split(".")[0]
    assert interpret.title == "Interpret and check"
    assert interpret.detail.startswith("The titles are a fixed lookup, so no AI judged them; ")
    assert "the names and the introduction are a fixed template" in interpret.detail
    assert "code added the shelter's confirmed answers" in interpret.detail
    assert (
        "classifier" not in interpret.detail and "checked that every place" not in interpret.detail
    )


def test_the_process_steps_name_the_classifier_and_the_ais_part_for_an_agent_profile(roster):
    from app.profile import FoundIn, PetVerdict

    p = agent_profile()
    p.order_source, p.ranked = "agent", []
    p.pet_entities[0].found_in = FoundIn(
        signal="x", kind="tv_show", position=2, out_of=20, by_tags=True
    )
    p.pet_entities[0].verdict = PetVerdict(
        pets=0.5, dogs=0.5, cats=0.1, family=0.9, real_people=0.05
    )
    facts, context, interpret = build_result_view(roster.get("dog-02"), LOCATION, p).process
    assert context.detail.startswith(
        f"Qloo returned lists of titles people around {LOCATION.label} tend to like, asked "
        "with its pet tags"
    )
    assert context.detail.endswith("Its ranking of the titles was unavailable.")
    assert interpret.detail.startswith(
        "A classifier (TypeSafe's Jev) sorted the titles in Qloo's lists and kept the clear "
        "pet titles; Namesake's AI judged 1 unclear title, added 1 title of its own, picked "
        "1 of the places to ask and set the order, as Qloo's ranking was unavailable; "
    )
    assert "kept a title only with Qloo's evidence for the area" in interpret.detail
    assert "checked that every place came from Qloo" in interpret.detail


def test_the_process_steps_for_an_empty_profile_promise_nothing(roster):
    p = LocationProfile(location_id=LOCATION.id)
    facts, context, interpret = build_result_view(roster.get("dog-02"), LOCATION, p).process
    assert context.detail == f"Qloo returned nothing for {LOCATION.label} yet."
    assert "fixed lookup" in interpret.detail


def test_the_process_steps_say_when_the_ais_own_titles_stayed_without_evidence(roster):
    # Decision 22: no evidence for any title keeps the AI's own, and the step says so, as
    # "Who chose" does; it never claims the titles were kept only with Qloo's evidence.
    p = agent_profile()
    p.titles_confirmed, p.ranked, p.order_source = False, [], "agent"
    for e in p.pet_entities:
        e.found_in = e.listed_in = None
    _, context, interpret = build_result_view(roster.get("dog-02"), LOCATION, p).process
    assert "Namesake's AI's own titles were kept" in interpret.detail
    assert "added 2 titles of its own" in interpret.detail
    assert "kept a title only with Qloo's evidence" not in interpret.detail
    assert "Its ranking of the titles was unavailable." in context.detail
    p.titles_confirmed = True
    _, _, interpret = build_result_view(roster.get("dog-02"), LOCATION, p).process
    assert "kept a title only with Qloo's evidence for the area" in interpret.detail


def test_the_process_steps_count_every_way_qloo_listed_a_title(roster):
    from app.profile import Entity, FoundIn

    p = agent_profile()
    p.ranked, p.venues, p.cells = [], [], []
    # Found by a search with one of its titles, not by the pet tags.
    p.pet_entities[0].found_in = FoundIn(
        signal="Example Cat Show", kind="tv_show", position=3, out_of=20
    )
    _, context, _ = build_result_view(roster.get("dog-02"), LOCATION, p).process
    assert context.detail.startswith(
        "Qloo returned lists of what people here who like its titles also tend to like"
    )
    assert "pet tags" not in context.detail
    # Listed in a better place elsewhere, and the area's own watched list, count too.
    p.pet_entities[0].found_in = None
    p.pet_entities[0].listed_in = FoundIn(
        signal="x", kind="movie", position=1, out_of=20, by_tags=True
    )
    p.local_tastes = [
        Entity(
            id="00000000-0000-4000-8000-00000000aa01",
            name="Example Local",
            type="urn:entity:tv_show",
        )
    ]
    _, context, _ = build_result_view(roster.get("dog-02"), LOCATION, p).process
    assert context.detail.startswith(
        f"Qloo returned lists of titles people around {LOCATION.label} tend to like, asked "
        f"with its pet tags and its list of titles watched around {LOCATION.label}."
    )
    assert "nothing" not in context.detail


def test_the_process_steps_count_the_place_cards_the_page_shows(roster):
    # A pick the code screens out, or skips for this animal, is not counted as picked.
    p = agent_profile()
    for v in p.venues:
        v.chosen_reason = "a reason"
    kids = next(v for v in p.venues if v.name == "Community Hall")
    kids.description = "A hall with a playgroup for children."
    cat = roster.get("cat-03").model_copy(deep=True)
    cat.checks.good_with_children = "no"
    view = build_result_view(cat, LOCATION, p)
    _, _, interpret = view.process
    assert f"picked {len(view.venues)} of the places to ask" in interpret.detail
    # The strip at the top says the same number as the step and the cards.
    assert f"picked {len(view.venues)} of the places to ask" in view.qloo_part.ai
    assert "Community Hall" not in [v.name for v in view.venues]
    everyone = build_result_view(roster.get("dog-02"), LOCATION, p)
    assert f"picked {len(everyone.venues)} of the places to ask" in everyone.process[2].detail
    assert f"picked {len(everyone.venues)} of the places to ask" in everyone.qloo_part.ai
    assert len(everyone.venues) == len(view.venues) + 1


def test_the_local_lead_follows_the_listings_state(roster):
    from app.agent.results import CHECKS_VERSION, ListingResult
    from tests.test_product import saved_listing

    animal = roster.get("dog-02")

    # The AI ran, but its draft failed the checks: the page falls back and says why.
    def fell_back(reason):
        return ListingResult(
            animal_id=animal.id,
            location_id=LOCATION.id,
            checks_version=CHECKS_VERSION,
            fallback_reason=reason,
        )

    failed = fell_back(
        "The draft from Namesake's AI did not pass the checks after one repair, so this is "
        "the templated listing."
    )
    view = build_result_view(animal, LOCATION, profile(), failed)
    assert view.story_lead.startswith("No local name yet: Namesake's AI's draft did not pass")
    # The pipeline's other two reasons are not a failed draft: the paper says which.
    for reason in [
        "No model is configured, so this is the templated listing.",
        "Qloo returned no titles to draw names from.",
    ]:
        view = build_result_view(animal, LOCATION, profile(), fell_back(reason))
        assert view.story_lead.startswith("No local name yet: the templated listing says why. ")
        assert view.listing.fallback_note == reason
    # A draft whose first name is a lookalike: Qloo found the title, the AI matched it.
    listing = saved_listing()
    listing.draft.names[0].source = "lookalike"
    view = build_result_view(animal, LOCATION, profile(), listing)
    assert view.story_lead.startswith("A name from a lookalike title Qloo found, matched by")
    # A pet-themed title with local evidence.
    view = build_result_view(animal, LOCATION, profile(), saved_listing())
    assert view.story_lead.startswith("A name from local taste data. ")
    assert view.story_lead_generic.startswith(
        "A common pet name from a fixed list, not from Qloo. "
    )


def test_the_leads_for_a_litter_named_as_a_set(roster):
    from app.views.models import LitterMateView
    from tests.test_product import saved_listing

    kitten = roster.get("kitten-01")
    mates = [
        LitterMateView(name="Bingo", url="/a", current=True),
        LitterMateView(name="Biscuit", url="/b"),
    ]
    view = build_result_view(kitten, LOCATION, profile(), saved_listing("kitten-01"), litter=mates)
    assert view.story_lead.startswith("A name from local taste data, one of a set for the litter. ")
    assert view.story_lead_generic.startswith(
        "A common pet name from a fixed list, not from Qloo and not a set. "
    )


def test_an_ais_own_title_qloo_listed_later_stays_the_ais_own(roster):
    # Codex, PR #37: listed_in marks local evidence, not who proposed the title.
    from app.profile import FoundIn

    p = agent_profile()
    before = build_result_view(roster.get("dog-02"), LOCATION, p)
    for e in p.pet_entities:
        if not e.found_in:
            e.listed_in = FoundIn(signal="x", kind="movie", position=4, out_of=20)
    after = build_result_view(roster.get("dog-02"), LOCATION, p)
    # The same "added N of its own" in the steps and the strip; the search that listed the
    # title later is the AI's too, and is said first.
    assert after.process[2].detail == before.process[2].detail.replace(
        "Namesake's AI ", "Namesake's AI searched Qloo's lists with x, ", 1
    )
    assert after.qloo_part.ai == "Searched Qloo's lists with x; " + (
        before.qloo_part.ai[0].lower() + before.qloo_part.ai[1:]
    )


def test_the_working_view_names_who_did_each_step(roster):
    from types import SimpleNamespace

    from app.agent.steps import StepLog
    from app.views.build import build_working_view

    log = StepLog()
    log.add("start", "Building the profile")
    log.add("qloo", "Asking Qloo")
    log.add("decision", "The litter's names will all come from a title")
    log.add("check", "Listing checked")
    log.add("note", "Using the saved profile")
    log.add("error", "The run stopped")
    log.add("done", "Done")
    run = SimpleNamespace(id="r1", result_url="/result?animal=dog-02&location=x", log=log)
    view = build_working_view(run, roster.get("dog-02"), LOCATION)
    log.add("note", "the classifier sorted the lists", actor="classifier")
    assert view.headline == "Writing her story…"
    view = build_working_view(run, roster.get("dog-02"), LOCATION)
    assert [s.actor for s in view.steps] == [
        "code", "qloo", "ai", "code", "code", "code", "code", "classifier"
    ]  # fmt: skip
    assert [s.label for s in view.steps][:3] == ["Code", "Qloo", "Namesake's AI"]
    assert view.steps[-1].label == "Classifier (TypeSafe's Jev)"
    assert view.actor_labels == {
        "qloo": "Qloo", "ai": "Namesake's AI",
        "classifier": "Classifier (TypeSafe's Jev)", "code": "Code",
    }  # fmt: skip
    assert [(k.actor, k.label) for k in view.actor_key] == list(view.actor_labels.items())
    him = build_working_view(run, roster.get("dog-01"), LOCATION)
    assert him.headline == "Writing his story…"


def test_a_step_takes_its_actor_from_the_site_or_from_its_kind():
    from app.agent.steps import StepLog, actor_for

    log = StepLog()
    assert log.add("qloo", "Asking Qloo").actor == "qloo"
    assert log.add("decision", "Chose a title").actor == "ai"
    assert log.add("note", "the classifier sorted the lists", actor="classifier").actor == (
        "classifier"
    )
    assert log.add("note", "Finishing the saved profile").actor == "code"
    for kind in ["start", "check", "note", "done", "error", "no-such-kind"]:
        assert actor_for(kind) == "code"


def test_the_classifier_and_the_comparison_are_never_logged_as_qloos():
    # The classifier's result and code's stand-out count were logged as Qloo's before.
    source = (
        pathlib.Path(__file__).parent.parent / "app" / "agent" / "profile_agent.py"
    ).read_text()
    assert 'actor="classifier"' in source
    assert '"qloo", f"{total} {what}: no classifier' not in source
    assert '"qloo", f"{len(venues)} places' not in source
    pipeline = (pathlib.Path(__file__).parent.parent / "app" / "agent" / "pipeline.py").read_text()
    assert '"qloo", f"Finishing the saved profile' not in pipeline


def test_a_typed_area_shows_its_name_alone():
    # Decision 29: a typed area has no region; one stored before keeps "Typed location".
    from app.views.build import location_option

    assert location_option(LOCATION).place == f"{LOCATION.label}, {LOCATION.region}"
    typed = LOCATION.model_copy(update={"label": "Williamsburg, Brooklyn", "region": ""})
    assert location_option(typed).place == "Williamsburg, Brooklyn"
    old = typed.model_copy(update={"region": "Typed location"})
    assert location_option(old).place == "Williamsburg, Brooklyn"
    assert location_option(old).region == ""  # the start page's shelter bar reads it


def test_the_plan_names_the_ais_picks_only_on_an_agent_profile(roster):
    p = agent_profile()
    for v in p.venues:
        v.chosen_reason = v.chosen_reason or "a community place"
    items = [i.text for i in build_result_view(roster.get("dog-02"), LOCATION, p).plan]
    ask = next(t for t in items if t.startswith("Ask "))
    assert ask.endswith(
        "(picked by Namesake's AI from Qloo's list) about hosting an adoption event or a flyer."
    )
    fixed = [i.text for i in build_result_view(roster.get("dog-02"), LOCATION, profile()).plan]
    assert not any("Namesake's AI" in t for t in fixed if t.startswith("Ask "))
