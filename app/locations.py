"""The preset shelter locations, loaded from `data/locations.json`.

`query` is the text sent to Qloo as the location signal. `city` is the wider
area for the heatmap, and the point is the fictional shelter's centre, never a
real shelter or street address.
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
    zoom: int = Field(default=13, ge=1, le=18)  # map zoom: ~14 for a neighbourhood, ~11 for a city
    # A channel beyond the usual audience, for the exposure plan. Our suggestion, not Qloo's.
    community_channel: str | None = None


def load_locations(path: Path) -> list[Location]:
    return [Location.model_validate(e) for e in json.loads(path.read_text(encoding="utf-8"))]
