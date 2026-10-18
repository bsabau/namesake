from app.profile import PROFILE_VERSION, build_profile, screen
from tests.qloo_fakes import (
    BASELINE,
    BASELINE_2,
    CAT_SHOW,
    DOG_SHOW,
    LOCATION,
    SEEDS,
    FakeQloo,
    describe_needs_input,
    envelope,
    key,
    standard_script,
)


def test_complete_profile():
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    assert p.complete and p.notes == []
    assert [e.id for e in p.pet_entities] == [DOG_SHOW, CAT_SHOW]
    assert [e.id for e in p.baselines] == [BASELINE, BASELINE_2] and p.baseline is None
    assert [e.id for e in p.map_titles] == [DOG_SHOW, CAT_SHOW] and p.version == PROFILE_VERSION


def test_ambiguous_seed_is_settled_by_its_rule_and_says_so():
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    dog = p.pet_entities[0]
    assert dog.id == DOG_SHOW
    assert dog.resolution == "chosen" and dog.alternatives == 1


def test_ambiguous_seed_without_a_single_match_is_left_out_not_forced():
    script = standard_script()
    issue = describe_needs_input()
    for c in issue.resolution.issues[0].candidates:
        c.description = "No year in this made-up description."
    script[key("describe", {"entity": "Example Dog Show", "type": "tv_show"})] = issue
    qloo = FakeQloo(script)
    p = build_profile(qloo, LOCATION, SEEDS)
    assert [e.id for e in p.pet_entities] == [CAT_SHOW]
    assert any("ambiguous" in n for n in p.notes)


def test_venues_are_compared_with_the_baseline():
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    by_name = {v.name: v for v in p.venues}
    assert by_name["Busy Arena"].baseline_rank == 1 and not by_name["Busy Arena"].distinctive
    assert by_name["Community Hall"].distinctive
    assert by_name["Community Hall"].contributions == {
        "Example Dog Show": 0.8,
        "Example Cat Show": 1.0,
    }


def test_without_the_baseline_no_venue_is_called_distinctive():
    script = standard_script()
    del script[
        key(
            "recommend",
            {
                "target_type": "place",
                "signals": [BASELINE, BASELINE_2],
                "filter_location": LOCATION.query,
                "limit": 15,
            },
        )
    ]
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert p.venues and not any(v.distinctive for v in p.venues)
    assert any("distinctive" in n for n in p.notes)


def test_unsuitable_venues_are_flagged():
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    assert {v.name: v.unsuitable for v in p.venues}["Hookah Corner"] == "hookah"
    assert screen("A neighbourhood arts centre.") is None
    assert screen("Upscale GENTLEMEN's club") == "gentlemen"


def test_lift_is_pet_minus_baseline_and_missing_where_unscored():
    p = build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)
    cells = {c.geohash: c for c in p.cells}
    # dr5rks5: pet maps 0.9 and 0.7, baseline maps 0.4 and 0.2, so 0.8 - 0.3.
    assert round(cells["dr5rks5"].lift, 3) == 0.5
    assert (cells["dr5rks5"].pet_count, cells["dr5rks5"].baseline_count) == (2, 2)
    # dr5rk66: only the dog show's map scored it, and no baseline did.
    assert cells["dr5rk66"].lift is None and cells["dr5rk66"].pet_count == 1


def test_errors_and_gaps_become_notes_not_crashes():
    script = standard_script()
    q = LOCATION.query
    script[key("where_popular", {"entity": DOG_SHOW, "within": q, "limit": 20})] = envelope(
        "where_popular",
        "error",
        error={"code": "QLOO_RATE_LIMIT", "layer": "qloo", "retryable": True, "recovery": "wait"},
    )
    for entity in (CAT_SHOW, BASELINE, BASELINE_2):
        del script[key("where_popular", {"entity": entity, "within": q, "limit": 20})]
    p = build_profile(FakeQloo(script), LOCATION, SEEDS)
    assert p.cells == [] and not p.complete
    assert any("QLOO_RATE_LIMIT" in n for n in p.notes)


def test_nothing_resolved_means_no_lookups():
    qloo = FakeQloo({})
    p = build_profile(qloo, LOCATION, SEEDS)
    assert p.pet_entities == [] and p.venues == []
    assert all(op == "describe" for op, _ in qloo.calls)
