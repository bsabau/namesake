"""Place lookups for the shelter's area: suggestions while typing, and the area around a
spot picked on the map. Photon (OpenStreetMap data, `geocoder_url`) answers both.

Only areas come back, never street addresses: cities, districts and neighbourhoods, named
the way the location field takes them ("Park Slope, Brooklyn"), so the name still goes
through `app/custom_location.py` and Qloo as typed (decision 12). Suggestions ask Photon
for areas only. A picked spot asks for whatever is nearest, usually a house or a street,
and keeps only the areas in its address, from the neighbourhood out to the city; the
nearest "area" itself can be a power station. The spot is rounded to about 100 m before
it leaves this server, and typed text the location field would refuse (digits, so street
addresses, or anything but a place name) is never sent at all.

Answers are cached in memory. Only a call that reaches Photon counts against the
allowances: each visitor's per minute, and one for everyone together, which keeps to
Photon's fair use. At most a few calls run at once, so a slow Photon never ties up the
server's threads. When Photon is slow, down or odd, the field works as typed.
"""

import http.client
import json
import math
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict, deque
from collections.abc import Callable

from pydantic import BaseModel

from app.custom_location import clean

LAYERS = ("city", "district", "locality")
USER_AGENT = "Namesake/0.1 (Qloo hackathon demo; https://namesake.bogdansabau.eu)"
TIMEOUT = 4
MAX_RESULTS = 5
MIN_QUERY = 3
# Three decimals of a degree: about 110 m north to south. Suggestions are ranked near
# the area on the map, which needs only one decimal (about 11 km).
SPOT_DECIMALS = 3
NEAR_DECIMALS = 1
# The pin kept in the visit: four decimals, about 11 m.
PIN_DECIMALS = 4
CACHE_SIZE = 1000
PER_MINUTE = 30
ALL_PER_MINUTE = 120
CONCURRENT = 4
# A pin further than this from the centre of Qloo's cells is not the same area.
MAX_PIN_KM = 30


class Throttled(Exception):
    """A lookup refused by the visitor's allowance or everyone's."""


class Place(BaseModel):
    label: str
    latitude: float
    longitude: float


def label_for(props: dict) -> str | None:
    """The area's name plus one wider place that tells it apart: "Park Slope, Brooklyn",
    "Austin, Texas". None when the name is one the location field would refuse."""
    name = props.get("name")
    if not name:
        return None
    wider = ("state",) if props.get("type") == "city" else ("district", "city", "state")
    context = next((props[k] for k in wider if props.get(k) and props[k] != name), None)
    return clean(f"{name}, {context}" if context else name)


def areas_around(props: dict) -> list[str]:
    """The areas a spot lies in, most local first: "Park Slope, Brooklyn", "Brooklyn, New
    York", "New York, New York". Read from the nearest object's address, never its name,
    unless the object is itself an area."""
    parts = {k: props.get(k) for k in ("locality", "district", "city", "state")}
    if props.get("type") in LAYERS:
        parts[props["type"]] = props.get("name")
    locality, district, city, state = parts.values()
    found = [
        locality and label_for({"name": locality, "district": district, "city": city}),
        district and label_for({"name": district, "city": city, "state": state}),
        city and label_for({"name": city, "type": "city", "state": state}),
    ]
    return list(dict.fromkeys(a for a in found if a))


Found = list[tuple[str, float, float]]  # (label, latitude, longitude)


def own_area(feature: dict) -> Found:
    """A suggestion: the area Photon found, at its own point."""
    lon, lat = (feature.get("geometry", {}).get("coordinates") or [None, None])[:2]
    label = label_for(feature.get("properties", {}))
    return [(label, lat, lon)] if label and lat is not None else []


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - https only
        return json.load(response)


class Places:
    def __init__(
        self,
        base_url: str | None,
        fetch: Callable[[str], dict] = fetch_json,
        overall: "Allowance | None" = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.fetch = fetch
        self.overall = overall or Allowance(ALL_PER_MINUTE)
        self._calls = threading.BoundedSemaphore(CONCURRENT)
        self._cache: OrderedDict[str, list[Place]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.base_url.startswith("https://")

    def search(
        self,
        text: str,
        near: tuple[float, float] | None = None,
        allow: Callable[[], bool] = lambda: True,
    ) -> list[Place]:
        """Areas whose names match what the visitor is typing, best first, and ranked near
        `near` (the area on the map) when given. `allow` is asked before Photon is."""
        text = " ".join(text.split())
        name = clean(text) if len(text) >= MIN_QUERY else None
        if not self.enabled or name is None:
            return []
        params: dict = {"q": name, "limit": MAX_RESULTS * 2, "lang": "en"}
        if near is not None:
            params |= {"lat": round(near[0], NEAR_DECIMALS), "lon": round(near[1], NEAR_DECIMALS)}
        return self._cached(self._url("api", params), own_area, allow)[:MAX_RESULTS]

    def at(
        self, latitude: float, longitude: float, allow: Callable[[], bool] = lambda: True
    ) -> list[Place]:
        """The areas a spot lies in, most local first, looked up at about 100 m. Each comes
        with the rounded spot, since an area's own centre is not known here."""
        if not self.enabled:
            return []
        lat, lon = round(latitude, SPOT_DECIMALS), round(longitude, SPOT_DECIMALS)
        url = self._url("reverse", {"lat": lat, "lon": lon, "limit": 1}, areas_only=False)
        return self._cached(
            url, lambda f: [(a, lat, lon) for a in areas_around(f.get("properties", {}))], allow
        )

    def _url(self, path: str, params: dict, areas_only: bool = True) -> str:
        layers = [("layer", x) for x in LAYERS] if areas_only else []
        return f"{self.base_url}/{path}?{urllib.parse.urlencode([*params.items(), *layers])}"

    def _cached(
        self, url: str, read: Callable[[dict], Found], allow: Callable[[], bool]
    ) -> list[Place]:
        """Places from one Photon answer, cached by URL; `read` turns each feature into
        (label, latitude, longitude). Raises Throttled when an allowance is spent."""
        with self._lock:
            if url in self._cache:
                self._cache.move_to_end(url)
                return self._cache[url]
        if not allow() or not self.overall.take("everyone"):
            raise Throttled
        if not self._calls.acquire(timeout=TIMEOUT):
            return []
        try:
            data = self.fetch(url)
            places: list[Place] = []
            for feature in data["features"]:
                for label, lat, lon in read(feature):
                    if label not in {p.label for p in places}:
                        places.append(Place(label=label, latitude=lat, longitude=lon))
        except (OSError, ValueError, http.client.HTTPException, LookupError, TypeError,
                AttributeError):  # fmt: skip
            return []  # down, cut off or an odd answer; not cached, so the next try may work
        finally:
            self._calls.release()
        with self._lock:
            self._cache[url] = places
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return places


class Allowance:
    """Lookups per visitor per minute, in memory: enough to type and click around, too
    few to use this server as a free geocoder."""

    def __init__(self, per_minute: int = PER_MINUTE):
        self.per_minute = per_minute
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def take(self, visitor: str) -> bool:
        now = time.monotonic()
        with self._lock:
            # Forget visitors with nothing in the last minute, so the map stays small.
            for key in [k for k, q in self._seen.items() if not q or q[-1] < now - 60]:
                del self._seen[key]
            times = self._seen.setdefault(visitor, deque())
            while times and times[0] < now - 60:
                times.popleft()
            if len(times) >= self.per_minute:
                return False
            times.append(now)
            return True
