"""A visitor's workspace on disk: the animals they added, their photos, and the listings
made for them alone, kept for `TTL` seconds after their last visit (decision 34).

The workspace is anonymous. Its key is the random ID in the visitor's cookie, and the
"Link to this workspace" carries the same ID: anyone with the link can open it, after
the page asks them to confirm.
It holds what the visitor typed about their animals and nothing about the visitor.
The spot picked on the map is not kept here: it stays in memory for the visit
(decision 17). Rows past their time are deleted on the next write.
"""

import json
import sqlite3
import time
from pathlib import Path

TTL = 7 * 24 * 3600
# A visit renews the workspace at most this often, so it is kept this much longer than
# `TTL` and never ends early (review of the workspace PR).
RENEW = 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_photos (
    workspace_id TEXT NOT NULL,
    animal_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (workspace_id, animal_id)
);
CREATE INDEX IF NOT EXISTS workspaces_last_seen ON workspaces (last_seen);
"""


class Workspaces:
    def __init__(self, path: Path, ttl: float = TTL):
        self.path = path
        self.ttl = ttl

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        db.executescript(SCHEMA)
        return db

    def load(self, workspace_id: str) -> tuple[dict, dict[str, tuple[str, bytes]]] | None:
        """The workspace's data and photos, if it exists and is still within its time."""
        db = self._connect()
        try:
            row = db.execute(
                "SELECT data_json FROM workspaces WHERE id = ? AND last_seen >= ?",
                (workspace_id, time.time() - self.ttl - RENEW),
            ).fetchone()
            if row is None:
                return None
            photos = {
                animal_id: (content_type, bytes(data))
                for animal_id, content_type, data in db.execute(
                    "SELECT animal_id, content_type, data FROM workspace_photos "
                    "WHERE workspace_id = ?",
                    (workspace_id,),
                )
            }
            try:
                data = json.loads(row[0])
            except ValueError:
                # A row that cannot be read is no workspace: the visit starts afresh.
                return None
            return (data, photos) if isinstance(data, dict) else None
        finally:
            db.close()

    def save(self, workspace_id: str, data: dict) -> None:
        """Write the workspace and mark it seen now; drop every workspace past its time."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO workspaces (id, data_json, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data_json = excluded.data_json, "
                "last_seen = excluded.last_seen",
                (workspace_id, json.dumps(data), time.time()),
            )
            self._expire(db)
            db.execute("COMMIT")
        finally:
            db.close()

    def touch(self, workspace_id: str) -> None:
        """A visit keeps the workspace for another `ttl` (and `RENEW`) from now."""
        db = self._connect()
        try:
            db.execute(
                "UPDATE workspaces SET last_seen = ? WHERE id = ?", (time.time(), workspace_id)
            )
        finally:
            db.close()

    def add_photo(
        self, workspace_id: str, animal_id: str, content_type: str, data: bytes, budget: int
    ) -> bool:
        """Keep the photo if every workspace's photos together stay within `budget`: the
        check and the write in one transaction, so two adds at once cannot both pass."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            held = db.execute(
                "SELECT COALESCE(SUM(LENGTH(data)), 0) FROM workspace_photos "
                "WHERE NOT (workspace_id = ? AND animal_id = ?)",
                (workspace_id, animal_id),
            ).fetchone()[0]
            if held + len(data) > budget:
                db.execute("ROLLBACK")
                return False
            db.execute(
                "INSERT OR REPLACE INTO workspace_photos VALUES (?, ?, ?, ?)",
                (workspace_id, animal_id, content_type, data),
            )
            db.execute("COMMIT")
            return True
        finally:
            db.close()

    def remove_photo(self, workspace_id: str, animal_id: str) -> None:
        db = self._connect()
        try:
            db.execute(
                "DELETE FROM workspace_photos WHERE workspace_id = ? AND animal_id = ?",
                (workspace_id, animal_id),
            )
        finally:
            db.close()

    def _expire(self, db: sqlite3.Connection) -> None:
        cutoff = time.time() - self.ttl - RENEW
        db.execute(
            "DELETE FROM workspace_photos WHERE workspace_id IN "
            "(SELECT id FROM workspaces WHERE last_seen < ?)",
            (cutoff,),
        )
        db.execute("DELETE FROM workspaces WHERE last_seen < ?", (cutoff,))
        # A photo is written after its workspace, so one without a workspace is left over.
        db.execute(
            "DELETE FROM workspace_photos WHERE workspace_id NOT IN (SELECT id FROM workspaces)"
        )
