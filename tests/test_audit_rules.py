"""Rules added after the final audits (19 October): species-aware venue signals, titles
whose own name does not suit a listing, the hook's screens, bully-type shorthand, and
references two animals may not share."""

import asyncio

from app.agent import checks
from app.agent.listing_agent import ListingDraft, open_title
from app.agent.pipeline import run_pipeline, taken_names, taken_references
from app.agent.profile_agent import ProfileDeps, other_species_only, species_first
from app.agent.results import CHECKS_VERSION, ListingResult
from app.agent.steps import StepLog
from app.profile import Entity, PetVerdict
from app.store import Store
from tests.qloo_fakes import CAT_SHOW, DOG_SHOW, LOCATION, SEEDS, FakeQloo
from tests.test_agents import DRAFT, PLAN, Script, _tmp_db, full_script


def deps_with(species, *entities):
    d = ProfileDeps(qloo=None, location=LOCATION, species=species, log=StepLog())
    for e in entities:
        d.titles_seen[e.id] = e
    return d


def verdict(dogs, cats):
    return PetVerdict(pets=0.9, dogs=dogs, cats=cats, family=0.9, real_people=0.0)


def test_a_dogs_venues_rest_on_dog_and_pet_titles_before_cat_ones():
    cat = Entity(id=CAT_SHOW, name="Nature Cat", type="urn:entity:tv_show")
    dog = Entity(id=DOG_SHOW, name="Bluey", type="urn:entity:tv_show")
    pets = Entity(id="p", name="Pet Rescue Stories", type="urn:entity:tv_show")
    d = deps_with("dog", cat, dog, pets)
    # No classifier verdict: the title's own animal words decide.
    assert other_species_only(d, CAT_SHOW) and not other_species_only(d, DOG_SHOW)
    assert species_first(d, [CAT_SHOW, DOG_SHOW, "p"]) == [DOG_SHOW, "p", CAT_SHOW]
    # With a verdict, the classifier decides: a cat show scored as about dogs too stays.
    cat.verdict = verdict(dogs=0.7, cats=0.9)
    assert not other_species_only(d, CAT_SHOW)
    cat.verdict = verdict(dogs=0.1, cats=0.9)
    assert other_species_only(d, CAT_SHOW)
    # For a cat profile a dog-only title goes last instead.
    dogs = Entity(id=DOG_SHOW, name="Dogs in Space", type="urn:entity:tv_show")
    assert species_first(deps_with("cat", cat, dogs), [DOG_SHOW, CAT_SHOW]) == [CAT_SHOW, DOG_SHOW]


def test_a_title_whose_own_name_does_not_suit_a_listing_gives_no_names():
    problems = checks.check_title("Smokey", "cat", "My Cat from Hell", "A reality series.")
    assert problems and "does not suit an adoption listing" in problems[0]
    assert not open_title(Entity(id="x", name="My Cat from Hell", type="urn:entity:tv_show"))
    assert checks.check_title("Bingo", "dog", "Bluey", "A puppy and her family.") == []
    # The description may mention a villain; only the title's own name counts.
    assert checks.check_title("Simba", "cat", "The Lion King", "Scar plots against him.") == []


def test_the_hook_screens_only_what_the_model_chose():
    title = "The Call of the Wild"
    assert checks.check_hook(f"Named after Buck, a dog in {title}.", title) == []
    trait = checks.check_hook("Named after Wild Buck, a dog in Example.", "Example")
    assert trait and "temperament" in trait[0]


def test_a_title_ending_in_an_exclamation_ends_the_hook():
    assert checks.hook_text("Scooby-Doo, a dog in Scooby Doo, Where Are You!") == (
        "Named after Scooby-Doo, a dog in Scooby Doo, Where Are You!"
    )
    assert checks.hook_text("Bingo, a puppy in Bluey") == "Named after Bingo, a puppy in Bluey."


def test_bully_type_shorthand_gets_the_strict_screen(roster):
    dog = roster.get("dog-02")
    for look in ("Pit mix, short coat", "A pittie", "staffy cross", "Bull terrier type"):
        assert checks.is_bully_type(dog.model_copy(update={"look": look})), look
    assert not checks.is_bully_type(dog.model_copy(update={"look": "A small spitz"}))


def saved(animal_id, name, character, entity_id=DOG_SHOW, version=CHECKS_VERSION):
    draft = ListingDraft.model_validate(
        {
            **DRAFT,
            "names": [
                {**DRAFT["names"][0], "name": name, "character": character, "entity_id": entity_id},
                *DRAFT["names"][1:],
            ],
        }  # fmt: skip
    )
    return ListingResult(
        animal_id=animal_id,
        location_id=LOCATION.id,
        checks_version=version,
        draft=draft,
        references=[f"{character}, a dog in Example Dog Show", "x", "y"],
    )


def test_a_reference_another_animal_is_named_after_is_sent_back(roster):
    store = Store(_tmp_db())
    store.put_listing(saved("dog-01", "Bing", "Bingo"))
    refs = taken_references(roster.get("dog-02"), LOCATION, store)
    assert refs == {(DOG_SHOW, ("bingo",)): "Bingo, a dog in Example Dog Show"}
    fixed = {**DRAFT, "names": [{**DRAFT["names"][0], "name": "Rex", "character": "Rex"},
                                *DRAFT["names"][1:]]}  # fmt: skip
    log = StepLog()
    result = asyncio.run(
        run_pipeline(
            roster.get("dog-02"),
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=store,
            seeds=SEEDS,
            model_factory=lambda: __import__(
                "pydantic_ai.models.function", fromlist=["FunctionModel"]
            ).FunctionModel(Script([PLAN], [DRAFT, fixed])),
            log=log,
        )
    )
    assert any("another animal at this shelter is named after" in s.text for s in log.steps)
    assert result.draft.names[0].name == "Rex"


def test_a_name_from_a_listing_saved_before_the_checks_changed_stays_taken(roster):
    store = Store(_tmp_db())
    store.put_listing(saved("dog-01", "Bing", "Bingo", version=CHECKS_VERSION - 1))
    assert store.get_listing("dog-01", LOCATION.id) is None  # not current
    assert "bing" in taken_names(roster.get("dog-02"), LOCATION, store)
    assert (DOG_SHOW, ("bingo",)) in taken_references(roster.get("dog-02"), LOCATION, store)


def test_a_reference_is_one_character_not_a_shared_first_word():
    key = checks.reference_key
    assert checks.same_reference(key("t", "Scooby"), key("t", "Scooby-Doo"))
    assert not checks.same_reference(key("t", "Mr Peanutbutter"), key("t", "Mr Pickles"))
    assert not checks.same_reference(key("t", "Bingo"), key("u", "Bingo"))
    assert not checks.same_reference(key("t", ""), key("t", "Bingo"))


def test_find_venues_asks_qloo_with_the_dog_title_first():
    from types import SimpleNamespace

    from app.agent.profile_agent import find_venues
    from app.profile import venue_input
    from tests.qloo_fakes import envelope, key
    from tests.test_venue_categories import CAFES

    script = {
        key("recommend", venue_input([DOG_SHOW, CAT_SHOW], LOCATION, True)): envelope(
            "recommend", results=CAFES
        )
    }
    d = ProfileDeps(
        qloo=FakeQloo(script, twins=False), location=LOCATION, species="dog", log=StepLog()
    )
    d.titles_seen[CAT_SHOW] = Entity(
        id=CAT_SHOW, name="Example Cat Show", type="urn:entity:tv_show"
    )
    d.titles_seen[DOG_SHOW] = Entity(
        id=DOG_SHOW, name="Example Dog Show", type="urn:entity:tv_show"
    )
    d.rank_order = [CAT_SHOW, DOG_SHOW]  # Qloo ranked the cat show first here
    out = find_venues(SimpleNamespace(deps=d), [CAT_SHOW, DOG_SHOW])
    assert out["asked_for"][0]["name"] == "Example Dog Show"
    asked = [i for op, i in d.qloo.calls if op == "recommend"]
    assert asked[0]["signals"] == [DOG_SHOW, CAT_SHOW]


def test_the_fixed_lookup_asks_with_the_animals_own_titles_first():
    from app.profile import build_profile
    from tests.qloo_fakes import standard_script

    for species, first in (("dog", DOG_SHOW), ("cat", CAT_SHOW)):
        p = build_profile(
            FakeQloo(standard_script()), LOCATION.model_copy(), SEEDS, species=species
        )
        assert p.venue_signals[0] == first, species
        assert sorted(p.venue_signals) == sorted([DOG_SHOW, CAT_SHOW])  # none dropped


def test_a_description_says_which_animal_when_the_name_does_not():
    from app.profile import about_other_species_only

    aristocats = Entity(
        id="a", name="The Aristocats", type="urn:entity:movie",
        description="A family of aristocratic cats in Paris.",
    )  # fmt: skip
    assert about_other_species_only(aristocats, "dog")
    assert not about_other_species_only(aristocats, "cat")
    both = aristocats.model_copy(update={"description": "Cats and dogs share a house."})
    assert not about_other_species_only(both, "dog")


def test_a_recheck_rebuilds_the_hook_and_refuses_an_unfit_title(roster):
    from app.agent.recheck import recheck
    from app.animals import Roster
    from app.profile import LocationProfile

    store = Store(_tmp_db())
    title = Entity(id=DOG_SHOW, name="Scooby Doo, Where Are You!", type="urn:entity:tv_show")
    cat = Entity(id=CAT_SHOW, name="Example Cat Show", type="urn:entity:tv_show")
    store.put_profile(
        LocationProfile(location_id=LOCATION.id, species="dog", pet_entities=[title, cat])
    )
    # dog-02: the draft's bio is written from its record, so only the screen can fail.
    old = saved("dog-02", "Bing", "Bingo", version=CHECKS_VERSION - 1)
    old.references = ["Bingo, a dog in Scooby Doo, Where Are You!", "x", "y"]
    old.hook = "Named after Bingo, a dog in Scooby Doo, Where Are You!."
    store.put_listing(old)
    kept, rerun = recheck(store, roster)
    assert (kept, rerun) == (1, 0)
    fresh = store.get_listing("dog-02", LOCATION.id)
    assert fresh.hook == "Named after Bingo, a dog in Scooby Doo, Where Are You!"
    # The same draft from a title whose own name does not suit a listing is left to rerun.
    hell = title.model_copy(update={"name": "My Dog from Hell"})
    store.put_profile(
        LocationProfile(location_id=LOCATION.id, species="dog", pet_entities=[hell, cat])
    )
    store.put_listing(saved("dog-02", "Bing", "Bingo", version=CHECKS_VERSION - 1))
    kept, rerun = recheck(store, Roster(animals=roster.animals, litters=roster.litters))
    assert (kept, rerun) == (0, 1) and store.get_listing("dog-02", LOCATION.id) is None


def test_one_draft_cannot_offer_one_character_twice(roster):
    store = Store(_tmp_db())
    twin = {**DRAFT, "names": [DRAFT["names"][0],
                               {**DRAFT["names"][2], "name": "Bing", "character": "Bingo Dog"},
                               DRAFT["names"][1]]}  # fmt: skip
    log = StepLog()
    from pydantic_ai.models.function import FunctionModel

    asyncio.run(
        run_pipeline(
            roster.get("dog-02"),
            LOCATION,
            qloo=FakeQloo(full_script()),
            store=store,
            seeds=SEEDS,
            model_factory=lambda: FunctionModel(Script([PLAN], [twin, DRAFT])),
            log=log,
        )
    )
    assert any("refer to one character" in s.text for s in log.steps)


def test_more_bully_type_spellings_and_a_title_used_as_a_name(roster):
    dog = roster.get("dog-02")
    for look in ("Pit-bull mix", "A Stafford cross", "One of the bullies"):
        assert checks.is_bully_type(dog.model_copy(update={"look": look})), look
    assert checks.check_character("Wild", "title")
    assert checks.check_character("Bluey", "title") == []


def test_a_litter_mate_awaiting_a_rerun_still_holds_the_litters_title():
    from app.agent.pipeline import litter_theme

    store = Store(_tmp_db())
    store.put_listing(saved("kitten-02", "Bing", "Bingo", version=CHECKS_VERSION - 1))
    assert litter_theme(LOCATION, store, {"kitten-02"}) == DOG_SHOW
