"""Profile version 2: the map combines the top pet titles, and the baseline is the area's
own top shows, leaving out pet-themed ones (decision 18). Fake Qloo, invented data only."""

from types import SimpleNamespace

from app.profile import Entity, baseline_from_tastes, build_profile, combine_cells
from app.upgrade_profiles import upgrade
from app.views.build import build_result_view
from tests.qloo_fakes import (
    BASELINE,
    BASELINE_2,
    CAT_SHOW,
    DOG_SHOW,
    LOCATION,
    SEEDS,
    FakeQloo,
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
    cells = {c.geohash: c for c in combine_cells([dog, cat], [drama])}
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


def profile():
    return build_profile(FakeQloo(standard_script()), LOCATION, SEEDS)


def test_the_map_names_both_pet_shows_and_carries_a_key(roster):
    view = build_result_view(roster.get("dog-02"), LOCATION, profile())
    shared = next(c for c in view.map.cells if c.geohash == "dr5rks5")
    assert "Example Dog Show and Example Cat Show" in shared.label
    assert "(2 shows)" in shared.label and "this area's top shows" in shared.label
    assert view.map.note and "Warm" in view.map.note
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
    new = upgrade(old, LOCATION, FakeQloo(standard_script()))
    assert new.version == 2 and [e.id for e in new.baselines] == [BASELINE, BASELINE_2]
    assert [e.id for e in new.pet_entities] == [DOG_SHOW, CAT_SHOW]
    assert new.made_by == "agent" and new.order_source == "qloo_rank" and new.species == "dog"
    assert all(v.chosen_reason == "a community arts centre" for v in new.venues)
    assert new.cells and new.local_tastes


def test_an_upgrade_qloo_cannot_finish_is_not_saved():
    script = standard_script()
    for entity in (DOG_SHOW, CAT_SHOW):
        del script[key("where_popular", {"entity": entity, "within": LOCATION.query, "limit": 20})]
    old = profile().model_copy(update={"version": 1, "baselines": [], "cells": []})
    assert upgrade(old, LOCATION, FakeQloo(script)) is None
