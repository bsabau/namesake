from PIL import Image

from app.config import ROOT

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
