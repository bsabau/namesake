"""What one visitor adds or changes: their workspace (decision 34).

Added animals, their photos, and listings made for this visitor alone (refined
versions, and listings for added animals) live here, never shared with other
visitors. Each session is held in memory for `TTL` seconds and written through to
its workspace on disk (app/workspace.py), kept for 7 days after the last visit, so it
survives a restart and opens from its link in another browser. The spot picked on the
map stays in memory only. The cookie holds a random ID and nothing else.
"""

import logging
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.agent.results import ListingResult
from app.animals import ADDED_PREFIX, Animal
from app.workspace import Workspaces

logger = logging.getLogger(__name__)

__all__ = ["ADDED_PREFIX"]

COOKIE = "namesake_session"
# Over HTTPS the cookie takes the __Host- prefix: only this host, over HTTPS, may set it.
SECURE_COOKIE = "__Host-namesake_session"
TTL = 2 * 3600
MAX_SESSIONS = 500
MAX_ANIMALS = 3
MAX_PHOTO_BYTES = 3 * 1024 * 1024
# All visitors' photos together, in memory (19 October audit: 500 sessions of three 3 MB
# photos could take the demo down). Past it, an add with a photo is refused, and the
# visitor may add the animal again without one.
PHOTO_BUDGET = 64 * 1024 * 1024

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
    # The spot the visitor picked on the map for the shelter, by location ID. Shown on
    # their maps only; Qloo gets the area's name, never this point.
    pins: dict[str, tuple[float, float]] = field(default_factory=dict)


def drop_listings(session: Session, animal_id: str) -> None:
    """Every listing made for this animal, and the requests behind them."""
    for key in [k for k in session.listings if k.split("@", 1)[0] == animal_id]:
        session.listings.pop(key, None)
        session.requests.pop(key, None)


def workspace_data(session: Session) -> dict:
    """What a workspace keeps on disk: never the map pin."""
    return {
        "animals": {k: a.model_dump(mode="json") for k, a in session.animals.items()},
        "listings": {k: r.model_dump(mode="json") for k, r in session.listings.items()},
        "requests": dict(session.requests),
    }


def session_from(session_id: str, data: dict, photos: dict[str, tuple[str, bytes]]) -> Session:
    """A session rebuilt from its workspace. An entry today's models no longer read is
    dropped, with the listings made for it, rather than failing the visit."""
    session = Session(id=session_id)
    for key, raw in data.get("animals", {}).items():
        try:
            session.animals[key] = Animal.model_validate(raw)
        except ValidationError:
            logger.warning("workspace animal no longer readable; dropped")
    for key, raw in data.get("listings", {}).items():
        try:
            session.listings[key] = ListingResult.model_validate(raw)
        except ValidationError:
            logger.warning("workspace listing no longer readable; dropped")
    session.requests = {k: v for k, v in data.get("requests", {}).items() if isinstance(v, str)}
    session.photos = {
        k: Photo(content_type=t, data=d) for k, (t, d) in photos.items() if k in session.animals
    }
    return session


class Sessions:
    def __init__(
        self,
        ttl: float = TTL,
        limit: int = MAX_SESSIONS,
        disk: Callable[[], Path | None] | None = None,
    ):
        self.ttl = ttl
        self.limit = limit
        self._items: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()
        # Where workspaces are written, read when needed so a test can point it elsewhere;
        # None keeps sessions in memory only.
        self._disk = disk or (lambda: None)

    def _workspaces(self) -> Workspaces | None:
        path = self._disk()
        return Workspaces(path) if path is not None else None

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(18)

    def get(self, session_id: str | None) -> Session | None:
        """The session with this ID, from memory or else from its workspace on disk, if
        any; looking it up keeps it alive."""
        if not session_id:
            return None
        with self._lock:
            self._expire()
            session = self._items.get(session_id)
            if session is not None and session.last_seen < time.monotonic() - self.ttl:
                del self._items[session_id]
                session = None
            if session is None:
                session = self._load(session_id)
                if session is None:
                    return None
                self._items[session_id] = session
                while len(self._items) > self.limit:
                    self._items.popitem(last=False)
            session.last_seen = time.monotonic()
            self._items.move_to_end(session_id)
            return session

    def _load(self, session_id: str) -> Session | None:
        workspaces = self._workspaces()
        if workspaces is None:
            return None
        found = workspaces.load(session_id)
        if found is None:
            return None
        # Opened again: kept another 7 days from now.
        workspaces.touch(session_id)
        return session_from(session_id, *found)

    def save(self, session: Session) -> None:
        """Write the session to its workspace, after any change to what it keeps."""
        workspaces = self._workspaces()
        if workspaces is not None:
            workspaces.save(session.id, workspace_data(session))

    def remove_animal(self, session: Session, animal_id: str) -> None:
        """The animal, its photo, and every listing made for it, gone from the workspace."""
        session.animals.pop(animal_id, None)
        session.photos.pop(animal_id, None)
        drop_listings(session, animal_id)
        self.save(session)
        workspaces = self._workspaces()
        if workspaces is not None:
            workspaces.remove_photo(session.id, animal_id)

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

    def _photo_bytes(self) -> int:
        return sum(len(p.data) for s in self._items.values() for p in s.photos.values())

    def add_photo(self, session: "Session", animal_id: str, photo: "Photo", budget: int) -> bool:
        """Keep the photo if every session's photos together stay within `budget`: the
        check and the store under one lock, so two adds at once cannot both pass. With
        workspaces on disk, the budget counts every workspace's photos there."""
        workspaces = self._workspaces()
        if workspaces is not None:
            self.save(session)  # the workspace first, so its photo is never left over
            if not workspaces.add_photo(
                session.id, animal_id, photo.content_type, photo.data, budget
            ):
                return False
            session.photos[animal_id] = photo
            return True
        with self._lock:
            self._expire()
            if self._photo_bytes() + len(photo.data) > budget:
                return False
            session.photos[animal_id] = photo
            return True

    def _expire(self) -> None:
        cutoff = time.monotonic() - self.ttl
        while self._items:
            oldest = next(iter(self._items.values()))
            if oldest.last_seen >= cutoff:
                break
            self._items.popitem(last=False)


def _workspace_db() -> Path | None:
    from app.config import get_settings

    return get_settings().workspace_db


SESSIONS = Sessions(disk=_workspace_db)
