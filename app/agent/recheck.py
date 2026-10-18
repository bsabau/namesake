"""Hold saved listings to today's checks after the checks change, with no live call.

    python -m app.agent.recheck

A draft saved under older checks is checked again against the animal's record (the bio
and the names' reasons) and the name screen, with the titles from the saved area profile.
One that passes is saved as current, with the confirmed checks
rebuilt from today's fixed sentences; one that fails, or that a
recheck of the record cannot cover (see app/agent/results.py), is left as it is and runs
again when next opened. deploy/deploy.sh runs this on every deploy.
"""

from app.agent import checks
from app.agent.listing_agent import record_problems, repeated_titles, screen_names, shown_bio
from app.agent.results import (
    CHECKS_VERSION,
    LOOKALIKE_LISTINGS_FROM,
    PLAIN_LISTINGS_FROM,
    ListingResult,
)
from app.animals import Animal, Roster, load_roster
from app.config import get_settings
from app.profile import Entity
from app.store import Store


def recheckable(result: ListingResult) -> bool:
    """Saved after the last change to any check other than the record checks."""
    lookalike = any(o.source == "lookalike" for o in result.draft.names)
    floor = LOOKALIKE_LISTINGS_FROM if lookalike else PLAIN_LISTINGS_FROM
    return result.checks_version >= floor


def screen_problems(store: Store, animal: Animal, result: ListingResult) -> list[str]:
    """The name screen on a saved draft, with its titles as Qloo returned them: the
    area profile's and the lookalikes'. A title no longer found counts as a problem."""
    profile = store.get_profile(result.location_id, animal.species)
    offered: dict[str, tuple[Entity, str]] = {}
    if profile is not None:
        offered = {e.id: (e, "pet") for e in profile.pet_entities}
        for e in profile.local_tastes:
            offered.setdefault(e.id, (e, "local"))
    offered |= {look.entity.id: (look.entity, "lookalike") for look in result.lookalikes}
    titles = {k: e for k, (e, _) in offered.items()}
    missing = [
        f"{o.name!r} has no title to check" for o in result.draft.names if o.entity_id not in titles
    ]
    # A litter named as a set takes its names from one title on purpose.
    strict = checks.is_bully_type(animal)
    repeats = [] if animal.litter else repeated_titles(result.draft.names, offered, strict)
    return missing + repeats + screen_names(result.draft.names, titles, strict)


def recheck(store: Store, roster: Roster) -> tuple[int, int]:
    """Saved drafts made current, and saved drafts left to run again."""
    kept = rerun = 0
    for result in store.saved_listings():
        if result.draft is None or result.checks_version == CHECKS_VERSION:
            continue
        # An animal added in a session is not in the roster; its listing runs again.
        animal = roster.get(result.animal_id)
        if (
            animal
            and recheckable(result)
            and not record_problems(animal, result.draft)
            and not screen_problems(store, animal, result)
        ):
            update = {"checks_version": CHECKS_VERSION, "bio": shown_bio(animal, result.draft)}
            store.put_listing(result.model_copy(update=update))
            kept += 1
        else:
            rerun += 1
    return kept, rerun


def main() -> None:
    settings = get_settings()
    kept, rerun = recheck(Store(settings.cache_db), load_roster(settings.animals_file))
    print(f"saved listings: {kept} pass today's checks, {rerun} will run again")


if __name__ == "__main__":
    main()
