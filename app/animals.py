"""The demo animals, loaded from `data/animals/animals.json`."""

import json
from pathlib import Path

from pydantic import BaseModel


class Animal(BaseModel):
    id: str
    species: str
    group: str
    sex: str
    age: str
    look: str
    temperament: str
    facts: list[str]
    image: str
    litter: str | None = None


class LitterPhoto(BaseModel):
    """A group photo of a litter. It has members instead of a profile."""

    id: str
    species: str
    litter: str
    members: list[str]
    image: str


class Roster(BaseModel):
    animals: list[Animal]
    litters: list[LitterPhoto]

    def get(self, animal_id: str) -> Animal | None:
        return next((a for a in self.animals if a.id == animal_id), None)


def load_roster(path: Path) -> Roster:
    animals, litters = [], []
    for entry in json.loads(path.read_text(encoding="utf-8")):
        if "members" in entry:
            litters.append(LitterPhoto.model_validate(entry))
        else:
            animals.append(Animal.model_validate(entry))
    return Roster(animals=animals, litters=litters)
