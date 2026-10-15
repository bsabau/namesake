"""The demo animals, loaded from `data/animals/animals.json`."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Answer = Literal["yes", "no", "unknown"]


class Checks(BaseModel):
    """What the shelter has confirmed. Anything not confirmed stays `unknown`."""

    good_with_children: Answer = "unknown"
    good_with_dogs: Answer = "unknown"
    good_with_cats: Answer = "unknown"
    house_trained: Answer = "unknown"
    bite_history: Answer = "unknown"


class Animal(BaseModel):
    id: str
    species: str
    group: str
    sex: str
    age: str
    look: str
    temperament: str
    # Present-tense observations; the only facts a listing may state.
    facts: list[str]
    # Backstory and time in the shelter: for staff, never printed in a listing.
    history: list[str] = Field(default_factory=list)
    checks: Checks = Field(default_factory=Checks)
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
