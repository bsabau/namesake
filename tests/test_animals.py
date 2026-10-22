import pytest
from PIL import Image

from app.animals import load_roster
from app.config import ROOT
from app.listing import MIN_WORDS, templated_listing

WEB_PHOTOS = ROOT / "app" / "static" / "animals"


def test_roster_splits_animals_from_litter_photos(roster):
    assert len(roster.litters) == 1
    litter = roster.litters[0]
    kittens = [a for a in roster.animals if a.litter == litter.litter]
    assert sorted(a.id for a in kittens) == sorted(litter.members)


def test_every_photo_has_a_web_sized_copy(roster):
    images = [a.image for a in roster.animals] + [lit.image for lit in roster.litters]
    for image in images:
        path = WEB_PHOTOS / image
        assert path.exists(), f"missing {path}; run scripts/make_web_photos.py"
        assert path.stat().st_size <= 150 * 1024
        with Image.open(path) as img:
            assert max(img.size) <= 800


# Codex, on the fuller records: the tests read a frozen roster, so these read the demo's own.
DEMO = load_roster(ROOT / "data" / "animals" / "animals.json")


@pytest.mark.parametrize("animal", DEMO.animals, ids=lambda a: a.id)
def test_every_demo_animal_fills_a_listing_and_keeps_something_to_learn(animal):
    assert templated_listing(animal).word_count >= MIN_WORDS
    assert "unknown" in animal.checks.model_dump().values()


def test_the_demo_kittens_are_house_trained_rather_than_saying_so_twice():
    kittens = [a for a in DEMO.animals if a.litter == "litter-a"]
    assert len(kittens) == 4
    for kitten in kittens:
        assert kitten.checks.house_trained == "yes"
        assert "uses the litter box" not in kitten.facts
