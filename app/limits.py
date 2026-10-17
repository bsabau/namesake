"""Limits on live work: runs that call the model or Qloo, and new custom locations.

Each visitor gets a few per hour, counted in memory and forgotten an hour after
the visitor's last start, so the table only ever holds the visitors active in the
last hour. The whole app gets a daily cap, counted in the cache database so a
restart does not reset it. Results that were made before cost nothing and are
never limited.

The lock makes check-and-count atomic within the one web process the app runs as.
"""

import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
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
        clock: Callable[[], float] = time.monotonic,
    ):
        db.parent.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.per_visitor = per_visitor_per_hour
        self.daily = {"run": runs_per_day, "location": locations_per_day}
        self.clock = clock
        # A visitor's starts in the last hour; a visitor with none has no entry.
        self._recent: dict[str, deque[float]] = {}
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
            if not recent:
                self._recent.pop(visitor, None)
            with sqlite3.connect(self.db, timeout=10) as conn:
                conn.execute(
                    "UPDATE usage SET count = max(count - 1, 0) WHERE day = ? AND kind = ?",
                    (_today(), kind),
                )

    def visitors_tracked(self) -> int:
        """How many visitors have a start in the last hour."""
        with self._lock:
            self._sweep()
            return len(self._recent)

    def _recent_for(self, visitor: str) -> deque[float]:
        """This visitor's starts in the last hour. Looking never creates an entry."""
        recent = self._recent.get(visitor)
        if recent is None:
            return deque()
        self._prune(recent)
        if not recent:
            del self._recent[visitor]
        return recent

    def _prune(self, recent: deque[float]) -> deque[float]:
        cutoff = self.clock() - 3600
        while recent and recent[0] < cutoff:
            recent.popleft()
        return recent

    def _sweep(self) -> None:
        """Forget every visitor whose last start is more than an hour old."""
        for visitor in [v for v, r in self._recent.items() if not self._prune(r)]:
            del self._recent[visitor]

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
        self._sweep()
        self._recent.setdefault(visitor, deque()).append(self.clock())
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
