"""Place lookups for the shelter's area: suggestions while typing, and the area around a
spot picked on the map. Photon (OpenStreetMap data, `geocoder_url`) answers both.

Venue pins (decision 4, revised) are the one exception: the server looks up the venues
Qloo returned, by their names and public street addresses, once per saved profile
(`venue_point`, `app/venue_points.py`). Otherwise only areas come back, never street
addresses: cities, districts and neighbourhoods, named
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
server's threads. When Photon is slow, down or odd, the field works as typed; a picked
spot says the lookup did not answer, so the visitor can pick it again.

A bare typed name Qloo resolves on its own is named the same way once it passes: the
spot looked up is the centre of Qloo's own cells, never anything the visitor picked
(`qloo_pick`, decision 38).
"""

import http.client
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict, deque
from collections.abc import Callable
from functools import cache
from time import sleep

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
MAX_PIN_KM = 15
# A venue match further than this from the shelter is some other place of that name.
VENUE_KM = 12
# Seconds between venue lookups (Photon's fair use).
PAUSE = 1.0


@cache
def places_for(url: str) -> "Places":
    """One lookup client per geocoder URL, shared by the routes and the runs."""
    return Places(url)


class LookupFailed(Exception):
    """Photon could not answer this time (down, slow, an odd answer): try again later."""


def same_name(asked: str, found: str) -> bool:
    """Whether a match carries the venue's name: its distinctive words (four letters or
    more), two of them when it has two or more, else the short name as whole words."""
    words = lambda text: {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}  # noqa: E731
    a, f = words(asked), words(found)
    if a:
        return len(a & f) >= min(2, len(a))
    short = re.escape(" ".join(re.findall(r"[a-z0-9]+", asked.lower())))
    return (
        bool(short)
        and re.search(rf"\b{short}\b", " ".join(re.findall(r"[a-z0-9]+", found.lower())))
        is not None
    )


class Throttled(Exception):
    """A lookup refused by the visitor's allowance or everyone's."""


def qloo_pick(
    places: "Places", text: str, latitude: float, longitude: float, visitor: str = "anyone"
) -> tuple[str | None, str | None]:
    """What a bare typed name ("Portland") became in Qloo, which picks one place on its
    own and does not say which: OpenStreetMap's areas at the centre of Qloo's cells. The
    one carrying the typed name and a wider place ("Portland, Oregon"), else the widest
    when it is not just the typed name, as (match, near). Both None when the lookup is
    off or did not answer; the area then keeps its name as typed (decision 38)."""
    try:
        areas = [place.label for place in places.at(latitude, longitude, visitor)]
    except (Throttled, LookupFailed):
        return None, None
    typed = text.strip().lower()
    # A label with no wider place ("Berlin", where the city is its own state) says no more
    # than was typed, so it is no match.
    match = next((a for a in areas if "," in a and a.split(",")[0].strip().lower() == typed), None)
    near = areas[-1] if areas and areas[-1].strip().lower() != typed else None
    return match, None if match else near


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


def _point(feature: dict) -> Found:
    lon, lat = (float(x) for x in feature["geometry"]["coordinates"][:2])
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return []  # an odd answer: no point
    return [(feature.get("properties", {}).get("name") or "", lat, lon)]


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - https only
        return json.load(response)


class Places:
    def __init__(
        self,
        base_url: str | None,
        fetch: Callable[[str], dict] = fetch_json,
        per_visitor: "Allowance | None" = None,
        overall: "Allowance | None" = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.fetch = fetch
        self.per_visitor = per_visitor or Allowance(PER_MINUTE)
        self.overall = overall or Allowance(ALL_PER_MINUTE)
        self._calls = threading.BoundedSemaphore(CONCURRENT)
        self.pause = PAUSE
        self._pace_lock = threading.Lock()
        self._last_venue = 0.0
        self._cache: OrderedDict[str, list[Place]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.base_url.startswith("https://")

    def search(
        self,
        text: str,
        near: tuple[float, float] | None = None,
        visitor: str = "anyone",
    ) -> list[Place]:
        """Areas whose names match what the visitor is typing, best first, and ranked near
        `near` (the area on the map) when given."""
        text = " ".join(text.split())
        name = clean(text) if len(text) >= MIN_QUERY else None
        if not self.enabled or name is None:
            return []
        params: dict = {"q": name, "limit": MAX_RESULTS * 2, "lang": "en"}
        if near is not None:
            params |= {"lat": round(near[0], NEAR_DECIMALS), "lon": round(near[1], NEAR_DECIMALS)}
        return self._cached(self._url("api", params), own_area, visitor)[:MAX_RESULTS]

    def at(self, latitude: float, longitude: float, visitor: str = "anyone") -> list[Place]:
        """The areas a spot lies in, most local first, looked up at about 100 m. Each comes
        with the rounded spot, since an area's own centre is not known here. Raises
        Throttled, or LookupFailed when Photon could not answer, so the visitor is told to
        try again rather than that the spot has no area."""
        if not self.enabled:
            return []
        lat, lon = round(latitude, SPOT_DECIMALS), round(longitude, SPOT_DECIMALS)
        url = self._url("reverse", {"lat": lat, "lon": lon, "limit": 1}, areas_only=False)
        return self._cached(
            url,
            lambda f: [(a, lat, lon) for a in areas_around(f.get("properties", {}))],
            visitor,
            strict=True,
            odd_fails=True,
        )

    def venue_point(
        self,
        name: str,
        address: str | None,
        near: tuple[float, float],
        visitor: str = "profile-build",
    ) -> Place | None:
        """Where a venue Qloo returned is: OpenStreetMap's best match for its name and
        address, else for the address alone, near the shelter. These are public business
        addresses from Qloo, looked up on the server when a profile is saved, never typed
        by a visitor. None when nothing close enough matches. A match by name and address
        must carry the venue's name (else it may be a neighbour), so the address alone is
        tried next. Raises Throttled, or LookupFailed when Photon could not answer, so the
        caller can try again later."""
        if not self.enabled:
            return None
        queries = [(f"{name}, {address}", True), (address, False)] if address else [(name, True)]
        for query, named in queries:
            params = {
                "q": " ".join(query.split())[:200],
                "limit": 1,
                "lat": round(near[0], NEAR_DECIMALS + 1),
                "lon": round(near[1], NEAR_DECIMALS + 1),
            }
            url = self._url("api", params, areas_only=False)
            found = self._cached(url, _point, visitor, strict=True, paced=True)
            if not found:
                continue
            point = found[0]
            if distance_km(near, (point.latitude, point.longitude)) > VENUE_KM:
                continue
            if named and not same_name(name, point.label):
                continue
            return point
        return None

    def _pace(self) -> None:
        """Venue lookups from every run, one at least `pause` seconds after the last, so
        concurrent profiles keep to Photon's fair use together."""
        with self._pace_lock:
            wait = self._last_venue + self.pause - time.monotonic()
            if wait > 0:
                sleep(wait)
            self._last_venue = time.monotonic()

    def _url(self, path: str, params: dict, areas_only: bool = True) -> str:
        layers = [("layer", x) for x in LAYERS] if areas_only else []
        return f"{self.base_url}/{path}?{urllib.parse.urlencode([*params.items(), *layers])}"

    def _cached(
        self,
        url: str,
        read: Callable[[dict], Found],
        visitor: str,
        strict: bool = False,
        paced: bool = False,
        odd_fails: bool = False,
    ) -> list[Place]:
        """Places from one Photon answer, cached by URL; `read` turns each feature into
        (label, latitude, longitude). Raises Throttled when an allowance is spent, and when
        `strict`, LookupFailed when Photon could not answer. Only a call that goes out is
        counted: one that waits too long for a slot is not. `paced` keeps venue lookups
        apart. An answer in an odd shape counts as no match, or with `odd_fails` raises
        LookupFailed too: `odd_fails` covers only the answer, `strict` the request."""
        with self._lock:
            if url in self._cache:
                self._cache.move_to_end(url)
                return self._cache[url]
        if not self._calls.acquire(timeout=TIMEOUT):
            if strict:
                raise LookupFailed("no free slot")
            return []
        try:
            if not self.overall.take("everyone"):
                raise Throttled
            if not self.per_visitor.take(visitor):
                self.overall.refund("everyone")
                raise Throttled
            if paced:
                self._pace()  # right before the request, so queued lookups keep apart
            try:
                data = self.fetch(url)
            except (OSError, http.client.HTTPException, ValueError) as exc:
                # Down, slow, refusing (a 429) or cut off mid-answer: a service failure,
                # not an answer.
                if strict:
                    raise LookupFailed(type(exc).__name__) from None
                raise
            places: list[Place] = []
            for feature in data["features"]:
                for label, lat, lon in read(feature):
                    if label not in {p.label for p in places}:
                        places.append(Place(label=label, latitude=lat, longitude=lon))
        except (OSError, ValueError, http.client.HTTPException, LookupError, TypeError,
                AttributeError):  # fmt: skip
            # Down, cut off or an odd answer; not cached, so the next try may work. For a
            # venue an odd answer counts as no match; for a picked spot it is a failure.
            if odd_fails:
                raise LookupFailed("odd answer") from None
            return []
        finally:
            self._calls.release()
        with self._lock:
            self._cache[url] = places
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return places


class Allowance:
    """Lookups per visitor per minute (or per `window` seconds), in memory: enough to
    type and click around, too few to use this server as a free geocoder."""

    def __init__(self, per_minute: int = PER_MINUTE, window: float = 60):
        # `per_minute` is the count allowed in each window: a minute unless `window`
        # gives another length in seconds.
        self.per_minute = per_minute
        self.window = window
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def take(self, visitor: str) -> bool:
        now = time.monotonic()
        with self._lock:
            # Forget visitors with nothing in the last window, so the map stays small.
            for key in [k for k, q in self._seen.items() if not q or q[-1] < now - self.window]:
                del self._seen[key]
            times = self._seen.setdefault(visitor, deque())
            while times and times[0] < now - self.window:
                times.popleft()
            if len(times) >= self.per_minute:
                return False
            times.append(now)
            return True

    def refund(self, visitor: str) -> None:
        """Give back the last lookup taken, for one that did not go out after all."""
        with self._lock:
            times = self._seen.get(visitor)
            if times:
                times.pop()
