"""Limits on live work: runs that call the model or Qloo, and new custom locations.

Each visitor gets a few per hour, counted in memory. The whole app gets a daily
cap, counted in the cache database so a restart does not reset it. Results that
were made before cost nothing and are never limited.

The lock makes check-and-count atomic within the one web process the app runs as.
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
            self._check(visitor, kind)
            self._record(visitor, kind)

    def refund(self, visitor: str, kind: Kind) -> None:
        """Give back a charge for work that turned out to need no live call."""
        with self._lock:
            recent = self._recent_for(visitor)
            if recent:
                recent.pop()
            with sqlite3.connect(self.db, timeout=10) as conn:
                conn.execute(
                    "UPDATE usage SET count = max(count - 1, 0) WHERE day = ? AND kind = ?",
                    (_today(), kind),
                )

    def _recent_for(self, visitor: str) -> deque[float]:
        recent = self._recent[visitor]
        now = time.monotonic()
        while recent and recent[0] < now - 3600:
            recent.popleft()
        return recent

    def _check(self, visitor: str, kind: Kind) -> None:
        if len(self._recent_for(visitor)) >= self.per_visitor:
            raise LimitReached(
                f"You have started {self.per_visitor} new runs in the last hour, the most "
                "one visitor can start. The examples and earlier results still open "
                "instantly."
            )
        if self._used_today(kind) >= self.daily[kind]:
            what = "new runs" if kind == "run" else "new locations"
            raise LimitReached(
                f"The demo has reached today's limit of {self.daily[kind]} {what}, which "
                "keeps it within its Qloo and model quota. The examples and earlier "
                "results still open instantly; new ones open again tomorrow (UTC)."
            )

    def _record(self, visitor: str, kind: Kind) -> None:
        self._recent_for(visitor).append(time.monotonic())
        with sqlite3.connect(self.db, timeout=10) as conn:
            conn.execute(
                "INSERT INTO usage VALUES (?, ?, 1) "
                "ON CONFLICT(day, kind) DO UPDATE SET count = count + 1",
                (_today(), kind),
            )

    def _used_today(self, kind: Kind) -> int:
        with sqlite3.connect(self.db, timeout=10) as conn:
            row = conn.execute(
                "SELECT count FROM usage WHERE day = ? AND kind = ?", (_today(), kind)
            ).fetchone()
        return row[0] if row else 0


def _today() -> str:
    return datetime.now(UTC).date().isoformat()
