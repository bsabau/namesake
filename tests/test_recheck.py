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
    save_profile(store, cat="A reality show about cat owners and Biscuit, their cat.")
    save(store, "dog-02", DRAFT, CHECKS_VERSION - 1)
    # "Biscuit" is a cat the show's description names, so an animal's own name: it passes.
    assert recheck(store, roster) == (1, 0)

    names = [{**DRAFT["names"][1], "role": "character"}, *DRAFT["names"][:1], DRAFT["names"][2]]
    save(store, "dog-02", {**DRAFT, "names": names}, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)


def test_a_saved_animal_name_a_real_people_title_does_not_name_runs_again(roster, tmp_path):
    # Version 16: the show may have no cat called Biscuit; nothing Qloo returned says so.
    store = Store(tmp_path / "store.sqlite")
    save_profile(store, cat="A reality show about a vet and the cats she treats.")
    save(store, "dog-02", DRAFT, CHECKS_VERSION - 1)
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


def test_an_older_draft_whose_reasons_cite_temperament_runs_again(roster, tmp_path):
    # Decided 18 October: a name's reason draws only on the recorded look.
    store = Store(tmp_path / "store.sqlite")
    names = [{**n, "why": "It suits a gentle dog."} for n in DRAFT["names"]]
    save(store, "dog-02", {**DRAFT, "names": names}, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)


def test_an_older_draft_with_two_names_from_one_title_runs_again_when_another_is_unused(
    roster, tmp_path
):
    # dog-01 is not bully-type: a local title is usable, so two names from one title rerun.
    store = Store(tmp_path / "store.sqlite")
    local = Entity(
        id="00000000-0000-4000-8000-0000000000aa",
        name="Example Puppy Club",
        type="urn:entity:tv_show",
        description="A made-up puppy training series.",
    )
    save_profile(store)
    profile = store.get_profile("x", "dog")
    store.put_profile(profile.model_copy(update={"local_tastes": [local]}))
    names = [{**n, "why": "It suits his yellow coat."} for n in DRAFT["names"]]
    save(store, "dog-01", {**DRAFT, "names": names, "bio": DOG_01_BIO}, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)


def test_a_bully_type_dog_may_repeat_a_title_once_its_pet_titles_are_used(roster, tmp_path):
    # dog-02 names only from pet titles; DRAFT uses both, so its repeat is allowed.
    store = Store(tmp_path / "store.sqlite")
    save(store, "dog-02", DRAFT, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (1, 0)


DOG_01_BIO = [{"text": "He is calm and gentle; a slow-walk companion.", "facts": ["temperament"]}]


def test_the_recheck_floors():
    # recheckable() reads only the names' sources: drafts older than a floor are rerun, since
    # a recheck cannot cover what changed before it.
    from app.agent.recheck import recheckable
    from app.agent.results import LOOKALIKE_LISTINGS_FROM, PLAIN_LISTINGS_FROM

    plain = ListingDraft.model_validate(DRAFT)
    look = ListingDraft.model_validate(
        {**DRAFT, "names": [*DRAFT["names"][:2], {**DRAFT["names"][2], "source": "lookalike"}]}
    )
    for draft, floor in ((plain, PLAIN_LISTINGS_FROM), (look, LOOKALIKE_LISTINGS_FROM)):
        for version, expected in ((floor - 1, False), (floor, True)):
            result = ListingResult(animal_id="dog-02", location_id="x", draft=draft,
                                   checks_version=version)  # fmt: skip
            assert recheckable(result) is expected
    assert (PLAIN_LISTINGS_FROM, LOOKALIKE_LISTINGS_FROM) == (5, 7)


def test_an_older_draft_with_an_unflattering_name_runs_again(roster, tmp_path):
    store = Store(tmp_path / "store.sqlite")
    names = [{**DRAFT["names"][0], "name": "Garbage", "character": "Garbage"}, *DRAFT["names"][1:]]
    save(store, "dog-02", {**DRAFT, "names": names}, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)


def test_an_older_draft_with_a_name_after_a_tragic_animal_runs_again(roster, tmp_path):
    # Version 15 refuses an animal that dies in its story, whatever role the model gave it.
    store = Store(tmp_path / "store.sqlite")
    save_profile(store)
    profile = store.get_profile("x", "dog")
    hooch = Entity(
        id="00000000-0000-4000-8000-0000000000ab",
        name="Turner & Hooch",
        type="urn:entity:movie",
        description="A made-up buddy film.",
    )
    store.put_profile(profile.model_copy(update={"local_tastes": [hooch]}))
    tragic = {**DRAFT["names"][0], "name": "Hooch", "character": "Hooch"}
    names = [tragic | {"entity_id": hooch.id, "source": "local"}, *DRAFT["names"][1:]]
    # Only the name screen fails: every reason is the plain one.
    names = [{**n, "why": "A short name, easy to say."} for n in names]
    save(store, "dog-01", {**DRAFT, "names": names, "bio": DOG_01_BIO}, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)
