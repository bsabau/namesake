"""Limits on live work: runs that call the model or Qloo, and new custom locations.

Each visitor gets a few per hour, counted in memory. The whole app gets a daily
cap, counted in the cache database so a restart does not reset it. Results that
were made before cost nothing and are never limited.
"""

import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

Kind = Literal["run", "location"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (day, kind)
)
"""


class LimitReached(Exception):
    """Refused; the message is worded for the visitor."""


class Limits:
    def __init__(
        self,
        db: Path,
        *,
        per_visitor_per_hour: int,
        runs_per_day: int,
        locations_per_day: int,
    ):
        db.parent.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.per_visitor = per_visitor_per_hour
        self.daily = {"run": runs_per_day, "location": locations_per_day}
        self._recent: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        with sqlite3.connect(db) as conn:
            conn.execute(SCHEMA)

    def charge(self, visitor: str, kind: Kind) -> None:
        """Count one piece of live work, or raise LimitReached without counting it."""
        with self._lock:
            now = time.monotonic()
            recent = self._recent[visitor]
            while recent and recent[0] < now - 3600:
                recent.popleft()
            if len(recent) >= self.per_visitor:
                raise LimitReached(
                    f"You have started {self.per_visitor} new runs in the last hour, the most "
                    "one visitor can start. The examples and earlier results still open "
                    "instantly."
                )
            self._charge_day(kind)
            recent.append(now)

    def _charge_day(self, kind: Kind) -> None:
        day = datetime.now(UTC).date().isoformat()
        conn = sqlite3.connect(self.db, isolation_level=None, timeout=10)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT count FROM usage WHERE day = ? AND kind = ?", (day, kind)
            ).fetchone()
            used = row[0] if row else 0
            if used >= self.daily[kind]:
                conn.execute("ROLLBACK")
                what = "new runs" if kind == "run" else "new locations"
                raise LimitReached(
                    f"The demo has reached today's limit of {self.daily[kind]} {what}, which "
                    "keeps it within its Qloo and model quota. The examples and earlier "
                    "results still open instantly; new ones open again tomorrow (UTC)."
                )
            conn.execute(
                "INSERT INTO usage VALUES (?, ?, 1) "
                "ON CONFLICT(day, kind) DO UPDATE SET count = count + 1",
                (day, kind),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()
