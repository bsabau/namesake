"""SQLite cache for harness results, keyed by operation and canonical input.

The database holds real Qloo data, so it lives outside git (`*.sqlite` is
ignored) and is deployed privately.
"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS qloo_cache (
    key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    input_json TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qloo_meta (
    name TEXT PRIMARY KEY,
    value REAL NOT NULL
)
"""


def canonical(input_: dict[str, Any]) -> str:
    return json.dumps(input_, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_key(operation: str, input_: dict[str, Any]) -> str:
    return hashlib.sha256(f"{operation}\n{canonical(input_)}".encode()).hexdigest()


class Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, operation: str, input_: dict[str, Any]) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT envelope_json FROM qloo_cache WHERE key = ?",
                (cache_key(operation, input_),),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, operation: str, input_: dict[str, Any], envelope: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO qloo_cache VALUES (?, ?, ?, ?, ?)",
                (
                    cache_key(operation, input_),
                    operation,
                    canonical(input_),
                    json.dumps(envelope),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def last_live_call(self) -> float | None:
        """When the harness was last called live, as a Unix time, by any process."""
        with self._connect() as db:
            row = db.execute("SELECT value FROM qloo_meta WHERE name = 'last_live_call'").fetchone()
        return row[0] if row else None

    def mark_live_call(self, when: float) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO qloo_meta VALUES ('last_live_call', ?)", (when,))
