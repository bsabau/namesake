"""app/agent/recheck.py: saved drafts held to today's record checks, with no live call."""

from app.agent.listing_agent import ListingDraft
from app.agent.recheck import recheck
from app.agent.results import CHECKS_VERSION, ListingResult
from app.store import Store
from tests.test_agents import DRAFT


def save(store: Store, animal: str, draft: dict, version: int) -> None:
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


def test_an_animal_added_in_a_session_runs_again(roster, tmp_path):
    store = Store(tmp_path / "store.sqlite")
    save(store, "added-1", DRAFT, CHECKS_VERSION - 1)
    assert recheck(store, roster) == (0, 1)
