"""What one visitor adds or changes, kept in memory for their session only.

Added animals, their photos, and listings made for this visitor alone (refined
versions, and listings for added animals) live here. Nothing is written to disk
or shared with other visitors; a session ends after `TTL` seconds without a
visit, or when the server restarts. The cookie holds a random ID and nothing else.
"""

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from app.agent.results import ListingResult
from app.animals import ADDED_PREFIX, Animal

__all__ = ["ADDED_PREFIX"]

COOKIE = "namesake_session"
# Over HTTPS the cookie takes the __Host- prefix: only this host, over HTTPS, may set it.
SECURE_COOKIE = "__Host-namesake_session"
TTL = 2 * 3600
MAX_SESSIONS = 500
MAX_ANIMALS = 3
MAX_PHOTO_BYTES = 3 * 1024 * 1024

# Only these formats, recognised from their first bytes, never from a name or a header.
PHOTO_TYPES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


def photo_type(data: bytes) -> str | None:
    for magic, content_type in PHOTO_TYPES.items():
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass
class Photo:
    content_type: str
    data: bytes


@dataclass
class Session:
    id: str
    last_seen: float = field(default_factory=time.monotonic)
    animals: dict[str, Animal] = field(default_factory=dict)
    photos: dict[str, Photo] = field(default_factory=dict)
    # Listings for this visitor alone, by result ID ("<animal>@<location>").
    listings: dict[str, ListingResult] = field(default_factory=dict)
    # The visitor's refine request behind each refined listing.
    requests: dict[str, str] = field(default_factory=dict)


class Sessions:
    def __init__(self, ttl: float = TTL, limit: int = MAX_SESSIONS):
        self.ttl = ttl
        self.limit = limit
        self._items: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(18)

    def get(self, session_id: str | None) -> Session | None:
        """The live session with this ID, if any; looking it up keeps it alive."""
        if not session_id:
            return None
        with self._lock:
            self._expire()
            session = self._items.get(session_id)
            if session is not None and session.last_seen < time.monotonic() - self.ttl:
                del self._items[session_id]
                return None
            if session is not None:
                session.last_seen = time.monotonic()
                self._items.move_to_end(session_id)
            return session

    def create(self) -> Session:
        """A new session under an ID the server made: a client never chooses its own."""
        return self.ensure(self.new_id())

    def ensure(self, session_id: str) -> Session:
        with self._lock:
            self._expire()
            session = self._items.get(session_id)
            if session is None:
                session = self._items[session_id] = Session(id=session_id)
                while len(self._items) > self.limit:
                    self._items.popitem(last=False)
            session.last_seen = time.monotonic()
            self._items.move_to_end(session_id)
            return session

    def _expire(self) -> None:
        cutoff = time.monotonic() - self.ttl
        while self._items:
            oldest = next(iter(self._items.values()))
            if oldest.last_seen >= cutoff:
                break
            self._items.popitem(last=False)


SESSIONS = Sessions()
