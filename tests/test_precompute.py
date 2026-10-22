"""The precompute script's job list (scripts/precompute_examples.py): offline, no runs."""

from app.animals import load_roster
from app.config import get_settings
from app.locations import load_locations
from app.views.build import EXAMPLES
from scripts.precompute_examples import plan


def setup():
    settings = get_settings()
    roster = load_roster(settings.animals_file)
    places = {x.id: x for x in load_locations(settings.locations_file)}
    return roster, places


def test_without_all_only_the_examples_are_built():
    roster, places = setup()
    assert plan(roster, places, False, set()) == list(EXAMPLES)
    assert all(loc == "astoria" for _, loc, _ in plan(roster, places, False, {"astoria"}))


def test_all_builds_every_animal_once_per_area_and_a_litter_once():
    roster, places = setup()
    jobs = plan(roster, places, True, set())
    assert jobs[: len(EXAMPLES)] == list(EXAMPLES)  # the examples keep their names
    singles = [a for a in roster.animals if a.litter is None]
    litters = {a.litter for a in roster.animals if a.litter}
    for location_id in places:
        here = [a for a, loc, _ in jobs if loc == location_id]
        assert sorted(a for a in here if roster.get(a).litter is None) == sorted(
            a.id for a in singles
        )
        assert len([a for a in here if roster.get(a).litter]) == len(litters)
    assert len(jobs) == len(places) * (len(singles) + len(litters))
    assert any(label == "the litter in Austin" for _, _, label in jobs)


def test_all_with_only_keeps_those_areas():
    roster, places = setup()
    jobs = plan(roster, places, True, {"barcelona"})
    assert jobs and {loc for _, loc, _ in jobs} == {"barcelona"}


def test_the_dry_run_lists_saved_and_missing_and_calls_nothing(monkeypatch, tmp_path, capsys):
    import asyncio
    import sys

    import scripts.precompute_examples as script
    from app.agent.results import CHECKS_VERSION, ListingResult
    from app.store import Store

    settings = get_settings()
    monkeypatch.setattr(settings, "cache_db", tmp_path / "cache.sqlite")
    Store(settings.cache_db).put_listing(
        ListingResult(animal_id="dog-02", location_id="park-slope", checks_version=CHECKS_VERSION)
    )

    def refuse(*args, **kwargs):
        raise AssertionError("a dry run sets up no model and no Qloo")

    monkeypatch.setattr(script, "model_factory", refuse)
    monkeypatch.setattr(script, "qloo_client", refuse)
    monkeypatch.setattr(sys, "argv", ["precompute", "--all", "--dry-run", "--only", "park-slope"])
    asyncio.run(script.main())
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "saved: The brindle dog in Park Slope"
    assert "build: the litter in Park Slope" in out
