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
