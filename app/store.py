"""Saved agent results: location profiles and listings, in the cache database.

They hold Qloo data and model output, so they live with the cache in `var/`,
which is git-ignored and deployed privately.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.agent.results import CHECKS_VERSION, ListingResult
from app.locations import Location
from app.profile import LocationProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_results (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


APPROVALS = """
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    animal_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    name TEXT NOT NULL,
    name_source TEXT NOT NULL,
    edited INTEGER NOT NULL,
    approved_at TEXT NOT NULL
)
"""


class Approval(BaseModel):
    """One approved listing, as the trial would record it. The text is not kept."""

    id: str
    animal_id: str
    location_id: str
    variant: str
    name: str
    # "generic list", or the Qloo source and title the name came from.
    name_source: str
    edited: bool
    approved_at: str


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute(SCHEMA)
            db.execute(APPROVALS)

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

    def _load(self, model: type[BaseModel], key: str):
        """A saved result, or None when missing or saved under an older shape (rerun it)."""
        data = self._get(key)
        if data is None:
            return None
        try:
            return model.model_validate(data)
        except ValidationError:
            return None

    def get_profile(self, location_id: str, species: str) -> LocationProfile | None:
        return self._load(LocationProfile, f"profile:{location_id}:{species}")

    def put_profile(self, profile: LocationProfile) -> None:
        self._put(f"profile:{profile.location_id}:{profile.species}", profile)

    def saved_profiles(self) -> list[tuple[str, str]]:
        """(location_id, species) of every saved profile, for app/upgrade_profiles.py."""
        with sqlite3.connect(self.path) as db:
            keys = [
                r[0] for r in db.execute("SELECT key FROM agent_results WHERE key LIKE 'profile:%'")
            ]
        return [tuple(k.removeprefix("profile:").rsplit(":", 1)) for k in keys]

    def get_listing(
        self, animal_id: str, location_id: str, current_only: bool = True
    ) -> ListingResult | None:
        result = self._load(ListingResult, f"listing:{animal_id}@{location_id}")
        return result if result is not None and (_current(result) or not current_only) else None

    def put_listing(self, result: ListingResult) -> None:
        self._put(f"listing:{result.animal_id}@{result.location_id}", result)

    def delete_listing(self, animal_id: str, location_id: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "DELETE FROM agent_results WHERE key = ?", (f"listing:{animal_id}@{location_id}",)
            )

    def listings_at(self, location_id: str, current_only: bool = True) -> list[ListingResult]:
        """Every saved listing for one shelter location; with `current_only` False, also
        those saved before the checks last changed, whose names are still in use."""
        with sqlite3.connect(self.path) as db:
            keys = [
                row[0]
                for row in db.execute(
                    "SELECT key FROM agent_results WHERE key LIKE ?", (f"listing:%@{location_id}",)
                )
            ]
        results = (self._load(ListingResult, k) for k in keys)
        return [r for r in results if r is not None and (_current(r) or not current_only)]

    def saved_listings(self) -> list[ListingResult]:
        """Every saved listing, current or not, for app/agent/recheck.py."""
        with sqlite3.connect(self.path) as db:
            keys = [
                row[0]
                for row in db.execute("SELECT key FROM agent_results WHERE key LIKE 'listing:%'")
            ]
        results = (self._load(ListingResult, k) for k in keys)
        return [r for r in results if r is not None]

    def get_location(self, location_id: str) -> Location | None:
        """A location a visitor typed and Qloo had data for."""
        return self._load(Location, f"location:{location_id}")

    def put_location(self, location: Location) -> None:
        self._put(f"location:{location.id}", location)

    def record_approval(self, approval: Approval) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval.id,
                    approval.animal_id,
                    approval.location_id,
                    approval.variant,
                    approval.name,
                    approval.name_source,
                    int(approval.edited),
                    approval.approved_at,
                ),
            )

    def approved_names(self, location_id: str) -> dict[str, set[str]]:
        """Names approved at one shelter location, by animal (lower case)."""
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT animal_id, name FROM approvals WHERE location_id = ?", (location_id,)
            ).fetchall()
        names: dict[str, set[str]] = {}
        for animal_id, name in rows:
            names.setdefault(animal_id, set()).add(name.lower())
        return names

    def approvals(self) -> list[Approval]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT * FROM approvals ORDER BY approved_at").fetchall()
        fields = list(Approval.model_fields)
        return [Approval.model_validate(dict(zip(fields, row, strict=True))) for row in rows]


def _current(result: ListingResult) -> bool:
    """Held to today's checks. A templated fallback has no draft and is always current."""
    return result.draft is None or result.checks_version == CHECKS_VERSION
