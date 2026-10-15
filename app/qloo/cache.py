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

    def reserve_live_slot(self, now: float, interval: float) -> float:
        """Claim the next start time for a live call, at least `interval` after the last.

        The read and the write happen in one write transaction, so two processes
        sharing the database never claim the same slot.
        """
        db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM qloo_meta WHERE name = 'last_live_call'").fetchone()
            start = now if row is None else max(now, row[0] + interval)
            db.execute("INSERT OR REPLACE INTO qloo_meta VALUES ('last_live_call', ?)", (start,))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return start
