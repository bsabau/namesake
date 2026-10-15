"""Saved agent results: location profiles and listings, in the cache database.

They hold Qloo data and model output, so they live with the cache in `var/`,
which is git-ignored and deployed privately.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from app.agent.results import ListingResult
from app.profile import LocationProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_results (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute(SCHEMA)

    def _get(self, key: str) -> dict | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT value_json FROM agent_results WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, key: str, value: BaseModel) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR REPLACE INTO agent_results VALUES (?, ?, ?)",
                (key, value.model_dump_json(), datetime.now(UTC).isoformat()),
            )

    def get_profile(self, location_id: str, species: str) -> LocationProfile | None:
        data = self._get(f"profile:{location_id}:{species}")
        return LocationProfile.model_validate(data) if data else None

    def put_profile(self, profile: LocationProfile) -> None:
        self._put(f"profile:{profile.location_id}:{profile.species}", profile)

    def get_listing(self, animal_id: str, location_id: str) -> ListingResult | None:
        data = self._get(f"listing:{animal_id}@{location_id}")
        return ListingResult.model_validate(data) if data else None

    def put_listing(self, result: ListingResult) -> None:
        self._put(f"listing:{result.animal_id}@{result.location_id}", result)
