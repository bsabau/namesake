"""The preset shelter locations, loaded from `data/locations.json`.

`query` is the text sent to Qloo as the location signal and the heatmap's area.
`city` names the wider city (only New York's rescue-partner plan item reads it), and
the point is the fictional shelter's centre, never a real shelter or street address.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field


class Location(BaseModel):
    id: str
    label: str
    region: str
    query: str
    city: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # Map zoom: ~14 for a neighbourhood, ~11 for a city as wide as Austin, ~13 for a compact one.
    zoom: int = Field(default=13, ge=1, le=18)


def load_locations(path: Path) -> list[Location]:
    return [Location.model_validate(e) for e in json.loads(path.read_text(encoding="utf-8"))]
