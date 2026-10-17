"""app/agent/recheck.py: saved drafts held to today's record checks, with no live call."""

from app.agent.listing_agent import ListingDraft
from app.agent.recheck import recheck
from app.agent.results import CHECKS_VERSION, ListingResult
from app.profile import Entity, LocationProfile
from app.store import Store
from tests.qloo_fakes import CAT_SHOW, DOG_SHOW
from tests.test_agents import DRAFT

SHOWS = {
    DOG_SHOW: ("Example Dog Show", "An animated series about a dog family."),
    CAT_SHOW: ("Example Cat Show", "An animated series about cats."),
}


def save_profile(store: Store, species: str = "dog", **descriptions: str) -> None:
    """The area profile a saved listing's titles come from; `descriptions` replaces a
    show's description, by "dog" or "cat"."""
    entities = []
    for kind, entity_id in (("dog", DOG_SHOW), ("cat", CAT_SHOW)):
        title, description = SHOWS[entity_id]
        entities.append(
            Entity(
                id=entity_id,
                name=title,
                type="urn:entity:tv_show",
                description=descriptions.get(kind, description),
            )
        )
    store.put_profile(LocationProfile(location_id="x", species=species, pet_entities=entities))


def save(store: Store, animal: str, draft: dict, version: int) -> None:
    if store.get_profile("x", "dog") is None:
        save_profile(store)
    store.put_listing(
        ListingResult(
            animal_id=animal,
            location_id="x",
            checks_version=version,
            draft=ListingDraft.model_validate(draft),
        )
    )


def puppy(draft: dict) -> dict:
    """The draft with an age word added to its first bio sentence."""
    first = draft["bio"][0]
    text = first["text"].replace("She is ", "She is a puppy, ", 1)
    return {**draft, "bio": [{**first, "text": text}, *draft["bio"][1:]]}


def test_an_older_draft_that_calls_an_adult_a_puppy_runs_again(roster, tmp_path):
    # Codex: version 8 allows "puppy" only under a year, and saved drafts skipped it.
    assert roster.get("dog-02").age.endswith("years")
    store = Store(tmp_path / "store.sqlite")
    save(store, "dog-02", puppy(DRAFT), CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)
    assert store.get_listing("dog-02", "x") is None


def test_a_draft_that_passes_is_saved_as_current_once(roster, tmp_path):
    store = Store(tmp_path / "store.sqlite")
    save(store, "dog-02", DRAFT, CHECKS_VERSION - 1)
    assert store.get_listing("dog-02", "x") is None
    assert recheck(store, roster) == (1, 0)
    assert store.get_listing("dog-02", "x").checks_version == CHECKS_VERSION
    assert recheck(store, roster) == (0, 0)


def test_a_rechecked_listing_shows_todays_confirmed_checks(roster, tmp_path):
    # Flash: the sentences code appends were kept as saved, in their old wording.
    from app.agent.listing_agent import shown_bio

    store = Store(tmp_path / "store.sqlite")
    save(store, "dog-02", DRAFT, CHECKS_VERSION - 1)
    recheck(store, roster)
    draft = ListingDraft.model_validate(DRAFT)
    assert store.get_listing("dog-02", "x").bio == shown_bio(roster.get("dog-02"), draft)


def test_an_animal_added_in_a_session_runs_again(roster, tmp_path):
    store = Store(tmp_path / "store.sqlite")
    save(store, "added-1", DRAFT, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)


def test_a_saved_name_from_a_title_about_real_people_runs_again(roster, tmp_path):
    # Version 9 screens the title a name comes from, with the saved profile's titles.
    store = Store(tmp_path / "store.sqlite")
    save_profile(store, cat="A reality show about cat owners.")
    save(store, "dog-02", DRAFT, CHECKS_VERSION - 1)
    # "Biscuit" is a cat in the show, so an animal's own name: it still passes.
    assert recheck(store, roster) == (1, 0)

    names = [{**DRAFT["names"][1], "role": "character"}, *DRAFT["names"][:1], DRAFT["names"][2]]
    save(store, "dog-02", {**DRAFT, "names": names}, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)


def test_a_saved_identity_coded_name_runs_again(roster, tmp_path):
    store = Store(tmp_path / "store.sqlite")
    names = [{**DRAFT["names"][0], "name": "Moses", "character": "Moses"}, *DRAFT["names"][1:]]
    save(store, "dog-02", {**DRAFT, "names": names}, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)


def test_a_saved_listing_without_its_profile_runs_again(roster, tmp_path):
    store = Store(tmp_path / "store.sqlite")
    store.put_listing(
        ListingResult(
            animal_id="dog-02",
            location_id="x",
            checks_version=CHECKS_VERSION - 1,
            draft=ListingDraft.model_validate(DRAFT),
        )
    )
    assert recheck(store, roster) == (0, 1)
