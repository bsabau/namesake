"""Profile versions 2 and 3: the map combines the top pet titles, a thin first one gives way
to the next, and the baseline is the area's own top shows, leaving out pet-themed ones
(decision 18). Fake Qloo, invented data only."""

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from app.agent.profile_agent import ProfileDeps, ProfilePlan, check_plan, find_venues
from app.agent.steps import StepLog
from app.profile import (
    PROFILE_VERSION,
    Entity,
    LiftCell,
    LocationProfile,
    averaged_cells,
    baseline_from_tastes,
    build_profile,
    combine_cells,
    finish_profile,
    needs_finishing,
    one_scale,
    profile_from,
    ranked_among,
)
from app.qloo.exec import QlooExecError
from app.views.build import build_result_view, map_view, why
from tests.qloo_fakes import (
    BASELINE,
    BASELINE_2,
    CAT_SHOW,
    DOG_SHOW,
    LOCAL_SHOWS,
    LOCATION,
    SEEDS,
    FakeQloo,
    cell,
    envelope,
    key,
    standard_script,
)


def scored(affinity: float, lat: float = 40.67, lon: float = -73.98):
    return SimpleNamespace(
        location=SimpleNamespace(latitude=lat, longitude=lon),
        query=SimpleNamespace(affinity=affinity),
    )


def test_cells_are_averaged_over_the_maps_that_scored_them():
    dog = {"a": scored(0.9), "b": scored(0.6)}
    cat = {"a": scored(0.7), "c": scored(0.5)}
    drama = {"a": scored(0.4), "c": scored(0.1)}
    cells = {c.geohash: c for c in averaged_cells([dog, cat], [drama])}
    assert set(cells) == {"a", "b", "c"}
    assert round(cells["a"].pet_score, 3) == 0.8 and cells["a"].pet_count == 2
    assert round(cells["a"].lift, 3) == 0.4 and cells["a"].baseline_count == 1
    assert cells["b"].lift is None and cells["b"].baseline_count == 0
    assert round(cells["c"].lift, 3) == 0.4


def test_the_baseline_leaves_out_pet_titles_and_shows_about_animals():
    def show(i: int, name: str, description: str = "A made-up show.") -> Entity:
        return Entity(id=f"id-{i}", name=name, type="urn:entity:tv_show", description=description)

    tastes = [
        show(1, "Example Puppy Club"),
        show(2, "Example Drama"),
        show(3, "Example Rescue", "A made-up series about a vet and the animals she treats."),
        show(4, "Example Bluey-like"),
        show(5, "Example Comedy"),
        show(6, "Example Quiz"),
    ]
    picked = [tastes[3]]  # a top show the AI picked as a pet title
    assert [e.name for e in baseline_from_tastes(tastes, picked)] == [
        "Example Drama",
        "Example Comedy",
    ]
    # Flash: animal words used as metaphors must not cost the area its baseline.
    metaphors = [show(7, "The Example Bear"), show(8, "Example Shark Tank")]
    assert len(baseline_from_tastes(metaphors, [])) == 2


def test_the_baseline_leaves_out_shows_tied_to_an_identity():
    # Hoboken, 18 October: a documentary about a president's portraits was a top show, so
    # the page said people there tend to like it, and it shaped the map.
    def show(i: int, name: str, description: str = "A made-up show.") -> Entity:
        return Entity(id=f"id-{i}", name=name, type="urn:entity:tv_show", description=description)

    tastes = [
        show(1, "Example Shore", "A made-up reality show at the beach."),
        show(2, "Picturing Example", "A made-up documentary about Obama's portraits."),
        show(3, "Example Sermons", "A made-up series of sermons about Christ."),
        show(4, "Example Comedy"),
    ]
    assert [e.name for e in baseline_from_tastes(tastes, [])] == [
        "Example Shore",
        "Example Comedy",
    ]
    # A cast surname in a description does not count (decision 19).
    harris = [show(5, "Example Days", "Starring Example Harris."), show(6, "Example Quiz")]
    assert len(baseline_from_tastes(harris, [])) == 2


def profile():
    return build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)


def test_the_map_names_both_pet_shows_and_carries_a_key(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    shared = next(c for c in view.map.cells if c.geohash == "dr5rks5")
    assert "Example Dog Show and Example Cat Show" in shared.label
    assert "(2 shows)" in shared.label and "this area's top shows" in shared.label
    assert view.map.note and "Warm" in view.map.note
    # Two sentences on the map itself (24 October): the colours, then the circle.
    colours, rest = view.map.note.split(". ")
    assert colours.startswith("Warm:") and "grey: no comparison" in colours
    assert rest.startswith("Circle: around the sample shelter")
    # The key names no baseline title; the Why panel does, as Qloo returned them.
    assert "Example Drama" not in view.map.note + view.map.legend
    reading = {item.title: item.detail for item in view.our_reading}
    detail = reading["Why compare with this area's top shows"]
    assert "Example Drama and Example Comedy" in detail and "Puppy" not in detail


def test_a_version_1_profile_still_renders(roster):
    old = profile().model_copy(
        update={
            "version": 1,
            "baselines": [],
            "map_titles": [],
            "baseline": Entity(
                id=BASELINE,
                name="Example Drama",
                type="urn:entity:tv_show",
                why="a widely watched drama with nothing to do with pets",
            ),
        }
    )
    view = build_result_view(roster.get("dog-02"), LOCATION, old)
    assert "fans of Example Drama" in view.map.legend
    assert "Example Cat Show" not in view.map.legend  # version 1 mapped one title
    assert any(i.title == "Why compare with Example Drama" for i in view.our_reading)


def test_an_upgrade_keeps_what_the_ai_chose():
    current = profile()
    old = current.model_copy(
        update={
            "version": 1,
            "baselines": [],
            "map_titles": [],
            "cells": [],
            "made_by": "agent",
            "order_source": "qloo_rank",
            "species": "dog",
            "local_tastes": [],
            "venues": [
                v.model_copy(update={"chosen_reason": "a community arts centre"})
                for v in current.venues
            ],
        }
    )
    new = finish_profile(old, LOCATION, FakeQloo(standard_script()), SEEDS)
    assert new.version == PROFILE_VERSION and [e.id for e in new.baselines] == [
        BASELINE,
        BASELINE_2,
    ]
    assert [e.id for e in new.pet_entities] == [DOG_SHOW, CAT_SHOW]
    assert new.made_by == "agent" and new.order_source == "qloo_rank" and new.species == "dog"
    assert all(v.chosen_reason == "a community arts centre" for v in new.venues)
    assert new.cells and new.local_tastes


def test_an_upgrade_qloo_cannot_finish_is_not_saved():
    script = standard_script()
    for entity in (DOG_SHOW, CAT_SHOW):
        del script[key("where_popular", {"entity": entity, "within": LOCATION.query, "limit": 20})]
    old = profile().model_copy(update={"version": 1, "baselines": [], "cells": []})
    assert finish_profile(old, LOCATION, FakeQloo(script), SEEDS) is None


def test_maps_of_different_precision_are_brought_to_the_coarsest():
    # muse, Flash: a 7-character pet map never met a 6-character baseline map.
    pets = {"dr5rks5": scored(0.8), "dr5rks6": scored(0.6), "dr5rk66": scored(0.5)}
    base = {"dr5rks": scored(0.3)}
    cells = {c.geohash: c for c in averaged_cells([pets], [base])}
    assert set(cells) == {"dr5rks", "dr5rk6"}
    assert round(cells["dr5rks"].pet_score, 3) == 0.7 and round(cells["dr5rks"].lift, 3) == 0.4


def test_a_long_description_counts_when_there_is_no_short_one():
    script = standard_script()
    tastes_key = key(
        "recommend", {"target_type": "tv_show", "signal_location": LOCATION.query, "limit": 10}
    )
    shows = [dict(s) for s in LOCAL_SHOWS]
    shows[1] = {**shows[1], "properties": {"description": "A family and their dog."}}
    script[tastes_key] = envelope("recommend", results=shows)
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert "Example Drama" not in [e.name for e in p.baselines]


@pytest.mark.parametrize("status", ["degraded", "partial", "needs_input"])
def test_an_unusable_list_of_top_shows_falls_back_to_the_seed_show(status):
    # Codex, muse, Flash: a degraded answer may have lost the area; needs_input has none.
    script = standard_script()
    tastes_key = key(
        "recommend", {"target_type": "tv_show", "signal_location": LOCATION.query, "limit": 10}
    )
    results = [] if status == "needs_input" else LOCAL_SHOWS
    script[tastes_key] = envelope("recommend", status, results=results, warnings=["thin"])
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert p.baseline_source == "seed" and [e.id for e in p.baselines] == [BASELINE]
    assert any("could not be used" in n for n in p.notes)


def test_a_missing_map_leaves_the_profile_unfinished_and_a_later_run_finishes_it():
    # Codex, Flash: an all-grey map was saved as complete when the baseline maps failed;
    # Codex: an unsaved profile would leave its listings without their titles' evidence.
    script = standard_script()
    missing = key("where_popular", {"entity": BASELINE_2, "within": LOCATION.query, "limit": 20})
    answer = script.pop(missing)
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert p.maps_missing == 1 and not p.complete
    qloo = FakeQloo({**script, missing: answer})
    finished = finish_profile(p.model_copy(update={"species": "dog"}), LOCATION, qloo, SEEDS)
    assert finished.complete and finished.species == "dog"
    # Only the missing map reached Qloo again; the fake serves the rest as the cache would.
    assert ("where_popular", missing[1]) in [(op, key(op, i)[1]) for op, i in qloo.calls]


def test_maps_that_never_overlap_still_finish():
    # Flash: with no shared cell nothing is missing, so the profile is finished, grey.
    script = standard_script()
    for entity in (BASELINE, BASELINE_2):
        k = key("where_popular", {"entity": entity, "within": LOCATION.query, "limit": 20})
        script[k] = envelope("where_popular", results=[cell_far()])
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert p.complete and all(c.lift is None for c in p.cells)


def cell_far() -> dict:
    return {
        "location": {"latitude": 40.70, "longitude": -73.90, "geohash": "dr5rzzz"},
        "query": {"affinity": 0.5, "popularity": 0.5},
    }


def test_version_1_cells_render_with_their_defaults(roster):
    old = profile().model_copy(
        update={
            "version": 1,
            "baselines": [],
            "map_titles": [],
            "baseline": Entity(id=BASELINE, name="Example Drama", type="urn:entity:tv_show"),
            "cells": [
                LiftCell.model_validate(
                    {"geohash": "dr5rks5", "latitude": 40.67, "longitude": -73.97,
                     "pet_score": 0.9, "baseline_score": 0.4}
                )
            ],
        }
    )  # fmt: skip
    label = build_result_view(roster.get("dog-02"), LOCATION, old).map.cells[0].label
    # One compared cell: on one scale there is nothing to rank it against.
    assert label == (
        "Scored for fans of Example Dog Show and fans of Example Drama: the only such cell, "
        "so nothing to compare it with."
    )


def deps_with_baseline() -> ProfileDeps:
    drama = Entity(id=BASELINE, name="Example Drama", type="urn:entity:tv_show")
    deps = ProfileDeps(
        qloo=FakeQloo(standard_script()),
        location=LOCATION,
        species="dog",
        log=StepLog(),
        baseline_titles={BASELINE: "Example Drama"},
    )
    deps.titles_seen[BASELINE] = drama
    return deps


def test_a_baseline_show_is_never_a_pet_title_or_a_venue_signal():
    # Codex, muse, Flash: the AI's venues were judged against a baseline the page did not
    # show, when it picked one of the area's top shows as a pet title.
    deps = deps_with_baseline()
    ctx = SimpleNamespace(deps=deps)
    assert "comparison uses" in find_venues(ctx, [BASELINE])["status"]
    plan = ProfilePlan.model_validate(
        {"titles": [{"entity_id": BASELINE, "why": "a show"}], "venues": []}
    )
    with pytest.raises(ModelRetry, match="cannot also be a pet-themed title"):
        check_plan(ctx, plan)


def test_the_pipeline_saves_an_unfinished_profile_and_finishes_it_next_run(roster):
    from app.store import Store
    from tests.test_agents import Script, _tmp_db, full_script, run

    store = Store(_tmp_db())
    script = full_script()
    missing = key("where_popular", {"entity": BASELINE_2, "within": LOCATION.query, "limit": 20})
    answer = script.pop(missing)
    run(Script([], []), roster, model=False, store=store, qloo=FakeQloo(script))
    saved = store.get_profile(LOCATION.id, "dog")
    assert saved is not None and not saved.complete
    _, _, log = run(
        Script([], []), roster, model=False, store=store, qloo=FakeQloo({**script, missing: answer})
    )
    assert store.get_profile(LOCATION.id, "dog").complete
    assert any("Finishing the saved profile" in s.text for s in log.steps)


def test_finishing_keeps_the_baseline_the_ai_chose_against():
    # Codex: finishing must not swap the comparison the AI's venue reasons were written for.
    p = profile()
    drama_only = [e for e in p.baselines if e.id == BASELINE]
    old = p.model_copy(update={"baselines": drama_only, "maps_missing": 1})
    script = standard_script()
    script[
        key(
            "recommend",
            {"target_type": "place", "signals": [BASELINE], "filter_location": LOCATION.query,
             "limit": 15},
        )
    ] = script[
        key(
            "recommend",
            {"target_type": "place", "signals": [BASELINE, BASELINE_2],
             "filter_location": LOCATION.query, "limit": 15},
        )
    ]  # fmt: skip
    new = finish_profile(old, LOCATION, FakeQloo(script), SEEDS)
    assert [e.id for e in new.baselines] == [BASELINE]


def test_a_profile_with_no_titles_is_not_saved(roster):
    # Codex, Flash: an empty profile would be "finished" forever without a call that helps.
    from app.store import Store
    from tests.test_agents import Script, _tmp_db, run

    store = Store(_tmp_db())
    run(Script([], []), roster, model=False, store=store, qloo=FakeQloo({}))
    assert store.get_profile(LOCATION.id, "dog") is None


def test_the_fallback_refills_its_baseline_when_a_seed_title_is_a_top_show():
    # Codex: a seed pet title among the area's top two was dropped, not replaced.
    kitchen = Entity(id=CAT_SHOW, name="Example Kitchen", type="urn:entity:tv_show")
    drama = Entity(id=BASELINE, name="Example Drama", type="urn:entity:tv_show")
    comedy = Entity(id=BASELINE_2, name="Example Comedy", type="urn:entity:tv_show")
    tastes = [kitchen, drama, comedy]
    prepared = (tastes, baseline_from_tastes(tastes, []), "area", [])
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS, prepared)
    assert [e.id for e in p.baselines] == [BASELINE, BASELINE_2] and p.complete


def test_a_finer_baseline_map_is_brought_to_the_pet_maps_precision():
    pets = {"dr5rks": scored(0.8)}
    base = {"dr5rks5": scored(0.4), "dr5rks6": scored(0.2)}
    cells = averaged_cells([pets], [base])
    assert [(c.geohash, round(c.lift, 3)) for c in cells] == [("dr5rks", 0.5)]


def test_a_map_with_no_shared_cell_says_so(roster):
    # Flash: the key promised warm and cool on an all-grey map, with no reason given.
    script = standard_script()
    for entity in (BASELINE, BASELINE_2):
        k = key("where_popular", {"entity": entity, "within": LOCATION.query, "limit": 20})
        script[k] = envelope("where_popular", results=[cell_far()])
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert any("no comparison" in n for n in p.notes)
    view = build_result_view(roster.get("dog-02"), LOCATION, p)
    assert view.map.note.startswith("Grey: no cell was scored for both")
    assert view.map.note.count(". ") == 1  # still two sentences
    assert not any(i.title == "Lift on the map" for i in view.our_reading)


def test_a_saved_profile_qloo_still_cannot_finish_is_used_as_it_is(roster):
    from app.store import Store
    from tests.test_agents import Script, _tmp_db, full_script, run

    store = Store(_tmp_db())
    script = full_script()
    del script[key("where_popular", {"entity": BASELINE_2, "within": LOCATION.query, "limit": 20})]
    run(Script([], []), roster, model=False, store=store, qloo=FakeQloo(script))
    _, _, log = run(Script([], []), roster, model=False, store=store, qloo=FakeQloo(script))
    assert any("could not finish it yet" in s.text for s in log.steps)


def test_the_seed_note_says_why_and_survives_finishing():
    # Flash: when every top show is a pet title, Qloo's list was used, not unusable;
    # Codex: finishing a profile kept its baseline but dropped this note.
    script = standard_script()
    tastes_key = key(
        "recommend", {"target_type": "tv_show", "signal_location": LOCATION.query, "limit": 10}
    )
    script[tastes_key] = envelope("recommend", results=[LOCAL_SHOWS[0]])  # a puppy show only
    script[
        key(
            "recommend",
            {"target_type": "place", "signals": [BASELINE], "filter_location": LOCATION.query,
             "limit": 15},
        )
    ] = script[
        key(
            "recommend",
            {"target_type": "place", "signals": [BASELINE, BASELINE_2],
             "filter_location": LOCATION.query, "limit": 15},
        )
    ]  # fmt: skip
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    note = next(n for n in p.notes if n.startswith("The comparison:"))
    assert "mentions animals, is one of the pet titles" in note
    finished = finish_profile(
        p.model_copy(update={"maps_missing": 1}), LOCATION, FakeQloo(script), SEEDS
    )
    assert note in finished.notes


def test_a_saved_comparison_the_screen_would_not_choose_is_chosen_again():
    # Codex, muse: profiles saved before the identity screen kept their comparison.
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    assert p.complete and not needs_finishing(p)
    doc = Entity(
        id="00000000-0000-4000-8000-000000000310",
        name="Example Portraits",
        type="urn:entity:tv_show",
        description="A made-up documentary about Obama's portraits.",
    )
    stale = p.model_copy(update={"baselines": [p.baselines[0], doc]})
    assert needs_finishing(stale)
    finished = finish_profile(stale, LOCATION, FakeQloo(standard_script()), SEEDS)
    assert [e.id for e in finished.baselines] == [BASELINE, BASELINE_2]
    assert not needs_finishing(finished)
    # The AI's titles are kept.
    assert [e.id for e in finished.pet_entities] == [e.id for e in p.pet_entities]


def test_everyday_religion_and_politics_words_count_in_descriptions_only():
    # Flash: "a Muslim family" or "a political satire" slipped through the name screen's
    # lists; a cast member called Christian or Church must not count.
    def show(i: int, name: str, description: str) -> Entity:
        return Entity(id=f"id-{i}", name=name, type="urn:entity:tv_show", description=description)

    tastes = [
        show(1, "Example Family", "A made-up comedy about a Muslim family in Michigan."),
        show(2, "Example Desk", "A made-up late-night political satire."),
        show(3, "Example Heist", "Starring Christian Example and Example Church."),
        show(4, "Example Quiz", "A made-up quiz show."),
    ]
    assert [e.name for e in baseline_from_tastes(tastes, [])] == ["Example Heist", "Example Quiz"]


def test_when_every_top_show_is_left_out_the_seed_stands_in_and_says_why():
    script = standard_script()
    tastes_key = key(
        "recommend", {"target_type": "tv_show", "signal_location": LOCATION.query, "limit": 10}
    )
    coded = {
        **LOCAL_SHOWS[1],
        "properties": {"short_description": "A made-up political talk show."},
    }
    script[tastes_key] = envelope("recommend", results=[coded])
    script[
        key(
            "recommend",
            {"target_type": "place", "signals": [BASELINE], "filter_location": LOCATION.query,
             "limit": 15},
        )
    ] = script[
        key(
            "recommend",
            {"target_type": "place", "signals": [BASELINE, BASELINE_2],
             "filter_location": LOCATION.query, "limit": 15},
        )
    ]  # fmt: skip
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert p.baseline_source == "seed"
    note = next(n for n in p.notes if n.startswith("The comparison:"))
    assert "mentions a religion, race or politics" in note


def test_the_page_never_names_a_saved_comparison_show_the_screen_rejects():
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    doc = Entity(
        id="00000000-0000-4000-8000-000000000311",
        name="Example Portraits",
        type="urn:entity:tv_show",
        description="A made-up documentary about Obama's portraits.",
    )
    stale = p.model_copy(update={"baselines": [p.baselines[0], doc]})
    returned, reading = why(LOCATION, stale)
    text = " ".join(f"{i.title} {i.detail}" for i in returned + reading)
    assert "Example Portraits" not in text and "Example Drama" in text
    compare = next(i for i in reading if i.title == "Why compare with this area's top shows")
    assert "is not named here; the next run chooses it again" in compare.detail

    both = stale.model_copy(update={"baselines": [doc, doc.model_copy(update={"id": "x2"})]})
    compare = next(i for i in why(LOCATION, both)[1] if i.title.startswith("Why compare"))
    assert compare.detail.startswith("The TV shows Qloo ranks highest")
    assert "They were chosen before that rule and are not named here" in compare.detail


def test_category_words_in_a_show_name_count_too():
    def show(i: int, name: str, description: str | None = None) -> Entity:
        return Entity(id=f"id-{i}", name=name, type="urn:entity:tv_show", description=description)

    tastes = [
        show(1, "The Example Election"),
        show(2, "Example Town", "A made-up drama about a conservative town."),
        show(3, "Example Quiz"),
        show(4, "Example Bake Off"),
    ]
    assert [e.name for e in baseline_from_tastes(tastes, [])] == [
        "Example Quiz",
        "Example Bake Off",
    ]


# The adaptive map: a thin first map title gives way to a spare one


EXTRA = Entity(
    id="00000000-0000-4000-8000-000000000330", name="Example Kitten Show", type="urn:entity:tv_show"
)
PETS = [
    Entity(id=DOG_SHOW, name="Example Dog Show", type="urn:entity:tv_show"),
    Entity(id=CAT_SHOW, name="Example Cat Show", type="urn:entity:tv_show"),
    EXTRA,
]
BASELINES = [
    Entity(id=BASELINE, name="Example Drama", type="urn:entity:tv_show"),
    Entity(id=BASELINE_2, name="Example Comedy", type="urn:entity:tv_show"),
]


def heat_key(entity_id):
    return key("where_popular", {"entity": entity_id, "within": LOCATION.query, "limit": 20})


def spread(n, row="x"):
    return [cell(f"dr5rk{k}{row}", 40.66 + k / 1000, -73.98, 0.5) for k in range(n)]


def adaptive(script, pets=PETS, signals=(DOG_SHOW, CAT_SHOW)):
    qloo = FakeQloo(script)
    return qloo, profile_from(qloo, LOCATION, pets, BASELINES, list(signals))


def test_a_thin_first_map_title_is_swapped_last_for_a_better_one(roster):
    # Hoboken, 18 October: the first map title had 1 cell there.
    script = standard_script()
    script[heat_key(EXTRA.id)] = envelope("where_popular", results=spread(6))
    qloo, p = adaptive(script)
    # The dog show's map has 2 cells, under the bar; the spare's makes the better map.
    assert [e.id for e in p.map_titles] == [EXTRA.id, CAT_SHOW]
    assert p.thin_map.title.id == DOG_SHOW and p.thin_map.cells == 2
    assert p.complete and p.maps_missing == 0 and len(p.cells) == 7
    heatmaps = [i["entity"] for op, i in qloo.calls if op == "where_popular"]
    # The comparison's maps come before the spare, so a refusal costs only the spare.
    assert heatmaps == [DOG_SHOW, BASELINE, BASELINE_2, CAT_SHOW, EXTRA.id]
    assert p.venue_signals == [DOG_SHOW, CAT_SHOW]  # the venues are not asked again
    legend = map_view(LOCATION, p).legend
    assert legend.startswith(
        "Qloo returned 2 map cells for Example Dog Show within Example Slope, so the map uses "
        "Example Kitten Show in its place. The places to ask are for fans of Example Dog Show "
        "and Example Cat Show. "
    )
    # The key on the map stays two sentences; the swap is said once, in the legend.
    assert "Example Kitten Show" not in map_view(LOCATION, p).note


def test_a_full_first_map_asks_for_no_spare():
    script = standard_script()
    script[heat_key(DOG_SHOW)] = envelope("where_popular", results=spread(5, "y"))
    qloo, p = adaptive(script)
    assert [e.id for e in p.map_titles] == [DOG_SHOW, CAT_SHOW] and p.thin_map is None
    assert ("where_popular", {"entity": EXTRA.id, "within": LOCATION.query, "limit": 20}) not in (
        qloo.calls
    )


def test_a_spare_with_more_cells_but_no_comparison_does_not_replace_the_one_that_has_it():
    # Flash, PR #14: swapping on cell count alone could lose the map's only lift.
    script = standard_script()
    script[heat_key(CAT_SHOW)] = envelope("where_popular", results=spread(2, "z"))
    script[heat_key(EXTRA.id)] = envelope("where_popular", results=spread(6))
    _, p = adaptive(script)
    assert [e.id for e in p.map_titles] == [DOG_SHOW, CAT_SHOW] and p.thin_map is None
    assert any(c.lift is not None for c in p.cells)


def test_a_refused_spare_leaves_the_map_as_it_was_and_says_why():
    _, p = adaptive(standard_script())  # the spare's heatmap is not cached: no answer
    assert [e.id for e in p.map_titles] == [DOG_SHOW, CAT_SHOW] and p.thin_map is None
    assert p.complete and p.maps_missing == 0
    # A call that never reached Qloo leaves no call row, so its note is the only trace.
    assert p.notes == ["Not precomputed yet: where fans of Example Kitten Show are, within "
                       "Example Slope."]  # fmt: skip


def test_a_spare_that_answered_but_was_no_better_is_marked_in_the_calls():
    script = standard_script()
    script[heat_key(EXTRA.id)] = envelope("where_popular", "empty")
    _, p = adaptive(script)
    assert p.thin_map is None and p.notes == []
    assert p.calls[-1].purpose.endswith("(tried for a thin map, not used)")


def test_a_map_qloo_could_not_place_is_empty_and_final():
    # Flash, PR #14 second re-check: needs_input is cached, so counting it missing would
    # have every later run try to finish the profile, forever. It arrives empty, with a note.
    script = standard_script()
    script[heat_key(BASELINE)] = envelope("where_popular", "needs_input")
    _, p = adaptive(script)
    assert p.maps_missing == 0 and p.complete and not needs_finishing(p)
    assert any("could not tell which place" in n for n in p.notes)


def test_an_upgrade_from_version_2_keeps_the_saved_comparison():
    _, p = adaptive(standard_script())
    old = p.model_copy(update={"version": 2, "baseline_source": "kept-for-test"})
    new = finish_profile(old, LOCATION, FakeQloo(standard_script()), SEEDS)
    assert new.version == PROFILE_VERSION and new.baseline_source == "kept-for-test"
    assert [e.id for e in new.baselines] == [BASELINE, BASELINE_2]


def test_an_empty_first_map_is_thin_too_and_the_profile_can_finish():
    # Codex, PR #14: an answered map with no cells used to count as missing, so the spare
    # was never tried and the profile could never finish.
    script = standard_script()
    script[heat_key(DOG_SHOW)] = envelope("where_popular", "empty")
    script[heat_key(EXTRA.id)] = envelope("where_popular", results=spread(6))
    _, p = adaptive(script)
    assert [e.id for e in p.map_titles] == [EXTRA.id, CAT_SHOW] and p.thin_map.cells == 0
    # The caption says it once; the gaps list does not repeat it.
    assert p.complete and "Qloo returned no map cells for Example Dog Show." not in p.notes
    assert "Qloo returned 0 map cells for" in map_view(LOCATION, p).legend


def test_one_cell_is_singular_on_the_page():
    script = standard_script()
    script[heat_key(DOG_SHOW)] = envelope("where_popular", results=spread(1, "q"))
    script[heat_key(EXTRA.id)] = envelope("where_popular", results=spread(6))
    _, p = adaptive(script)
    assert "returned 1 map cell for Example Dog Show" in map_view(LOCATION, p).legend


def test_with_no_spare_title_the_thin_map_stays():
    _, p = adaptive(standard_script(), pets=PETS[:2])
    assert [e.id for e in p.map_titles] == [DOG_SHOW, CAT_SHOW] and p.thin_map is None


def test_a_version_2_profile_is_upgraded_for_the_thin_map_check():
    _, p = adaptive(standard_script())
    assert not needs_finishing(p)
    assert needs_finishing(p.model_copy(update={"version": 2}))


def test_a_first_map_qloo_could_not_place_is_thin_and_gives_way():
    script = standard_script()
    script[heat_key(DOG_SHOW)] = envelope("where_popular", "needs_input")
    script[heat_key(EXTRA.id)] = envelope("where_popular", results=spread(6))
    _, p = adaptive(script)
    assert p.thin_map.title.id == DOG_SHOW and p.thin_map.cells == 0 and p.complete


def test_a_spare_that_errs_keeps_its_note_with_the_code():
    script = standard_script()
    script[heat_key(EXTRA.id)] = envelope(
        "where_popular",
        "error",
        error={"code": "QLOO_RATE_LIMIT", "layer": "api", "retryable": True, "recovery": "wait"},
    )
    _, p = adaptive(script)
    assert p.calls[-1].purpose.endswith("(tried for a thin map, not used)")
    assert any("QLOO_RATE_LIMIT" in n for n in p.notes)


def test_a_spare_qloo_could_not_place_is_marked_as_not_used():
    script = standard_script()
    script[heat_key(EXTRA.id)] = envelope("where_popular", "needs_input")
    _, p = adaptive(script)
    assert p.thin_map is None and p.complete
    assert p.calls[-1].status == "needs_input"
    assert p.calls[-1].purpose.endswith("(tried for a thin map, not used)")


def test_a_place_qloo_cannot_map_is_finished_once_with_one_note():
    # Flash, PR #14 third re-check: needs_input is about the place, so every map gets it;
    # the profile must not be finished again on every run.
    script = standard_script()
    for entity in (DOG_SHOW, CAT_SHOW, BASELINE, BASELINE_2, EXTRA.id):
        script[heat_key(entity)] = envelope("where_popular", "needs_input")
    _, p = adaptive(script)
    assert p.cells == [] and p.maps_missing == 0 and p.complete and not needs_finishing(p)
    assert sum("could not tell which place" in n for n in p.notes) == 1


def test_a_swapped_unplaced_map_says_so_in_the_caption():
    script = standard_script()
    script[heat_key(DOG_SHOW)] = envelope("where_popular", "needs_input")
    script[heat_key(EXTRA.id)] = envelope("where_popular", results=spread(6))
    _, p = adaptive(script)
    assert p.thin_map.unplaced
    assert not any("could not tell which place" in n for n in p.notes)  # the map has cells
    assert map_view(LOCATION, p).legend.startswith(
        "Qloo could not place Example Dog Show's map within Example Slope, so the map uses "
        "Example Kitten Show in its place."
    )


def test_a_swap_keeps_the_place_note_while_a_comparison_map_is_unplaced():
    # Codex, PR #14: the note must stay while a map still in use could not be placed.
    script = standard_script()
    for entity in (DOG_SHOW, BASELINE, BASELINE_2):
        script[heat_key(entity)] = envelope("where_popular", "needs_input")
    script[heat_key(EXTRA.id)] = envelope("where_popular", results=spread(6))
    _, p = adaptive(script)
    assert p.thin_map is not None
    assert sum("could not tell which place" in n for n in p.notes) == 1


def test_both_sides_are_ranked_among_the_cells_scored_for_both():
    # 22 October: the top shows are mapped far more widely, so their raw scores sat near
    # the top in every cell and every lift was below zero. On one scale they compare.
    pets = {"a": scored(0.9), "b": scored(0.6), "c": scored(0.2), "d": scored(0.4)}
    base = {"a": scored(0.93), "b": scored(0.99), "c": scored(0.95)}
    raw = {c.geohash: c for c in averaged_cells([pets], [base])}
    assert all(c.lift < 0 for c in raw.values() if c.lift is not None)
    cells = {c.geohash: c for c in combine_cells([pets], [base])}
    # Among a, b and c: pets rank a, b, c; the top shows rank b, c, a.
    assert [round(cells[g].pet_score, 3) for g in "abc"] == [0.833, 0.5, 0.167]
    assert [round(cells[g].baseline_score, 3) for g in "abc"] == [0.167, 0.833, 0.5]
    assert cells["a"].lift > 0 and cells["b"].lift < 0 and cells["c"].lift < 0
    # A cell with no comparison keeps its score and still has no lift.
    assert cells["d"].pet_score == 0.4 and cells["d"].lift is None


def test_one_scale_ties_share_a_place_and_ranking_again_changes_nothing():
    assert ranked_among([0.5, 0.5, 0.9]) == [1 / 3, 1 / 3, 5 / 6]
    pets = {"a": scored(0.9), "b": scored(0.3)}
    base = {"a": scored(0.8), "b": scored(0.8)}
    cells = combine_cells([pets], [base])
    assert [c.baseline_score for c in cells] == [0.5, 0.5]
    assert one_scale(cells) == cells


def test_a_saved_profile_loads_on_one_scale():
    raw = averaged_cells(
        [{"a": scored(0.9), "b": scored(0.4)}], [{"a": scored(0.99), "b": scored(0.97)}]
    )
    saved = LocationProfile(location_id="x", cells=raw).model_dump(mode="json")
    loaded = LocationProfile.model_validate(saved)
    assert [round(c.lift, 3) for c in loaded.cells] == [0.0, 0.0]


def test_a_qloo_failure_note_carries_no_error_text():
    # 22 October walkthrough: the note named what went wrong inside the harness.
    class Failing(FakeQloo):
        def run(self, operation, input_):
            raise QlooExecError("qloo exec exited 1: a detail for the server log")

    p = profile_from(Failing(standard_script()), LOCATION, PETS, BASELINES, [DOG_SHOW, CAT_SHOW])
    assert p.notes and all("detail for the server log" not in n for n in p.notes)
    assert any(n.startswith("Qloo could not be reached for ") for n in p.notes)
