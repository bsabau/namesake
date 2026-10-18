"""A location the visitor types: sent to Qloo as typed, and checked before any run.

A fixed heatmap decides whether the place is usable: where fans of the area's own
most-watched TV show are, within the typed place. That show comes from the call the
profile's local tastes make, so the profile finds it cached. When that list is not a
plain answer, or its top show is thin there, the seed show is heatmapped too and the
fuller map decides (decision 12). Passing says Qloo has data for the area, not that its
pet titles will map well; the result page says when the map is thin. A US seed show alone
left neighbourhoods abroad looking thin: Gràcia, Barcelona had 2 cells for it and 20 for
its own top show (docs/qloo-findings.md). Qloo returns no coordinates for a place name, so the map
centre and zoom come from the cells it returns.

- Qloo offers candidates (`needs_input`): the visitor picks one, as buttons.
- Too few cells: the data is thin there, and the app says so instead of
  producing a weak result.
"""

import hashlib
import math
import re
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.locations import Location
from app.profile import HEATMAP_LIMIT, Seeds, resolve_baseline
from app.qloo.envelope import Envelope
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss

PREFIX = "custom-"
MIN_CELLS = 5
MAX_LENGTH = 80
# Place names only: letters, spaces and light punctuation. Digits are refused, which
# keeps street addresses (and anything personal they carry) away from Qloo.
ALLOWED = re.compile(r"^[^\W\d_][\w .,'’()\-]*$")


class LocationCheck(BaseModel):
    status: Literal["ok", "needs_input", "thin", "unavailable", "invalid"]
    message: str = ""
    location: Location | None = None
    # Qloo's suggestions when it could not resolve the text, as distinct names.
    candidates: list[str] = []


def clean(text: str) -> str | None:
    text = " ".join(text.split())
    if (
        not 2 <= len(text) <= MAX_LENGTH
        or not ALLOWED.match(text)
        or any(ch.isdigit() or ch == "_" for ch in text)
    ):
        return None
    return text


def location_id(text: str) -> str:
    return PREFIX + hashlib.sha1(text.lower().encode()).hexdigest()[:10]


def zoom_for(lat_span: float, lon_span: float, latitude: float) -> int:
    """A map zoom that fits the cells: about 14 for a neighbourhood, 11 for a city."""
    span = max(lat_span, lon_span * math.cos(math.radians(latitude)), 0.005)
    return max(9, min(15, int(math.log2(360 / span)) + 1))


def local_top_show(qloo: QlooClient, text: str) -> str | None:
    """The TV show Qloo ranks highest for people around the typed place, or None when the
    answer is not a plain list. The input matches the profile's local-tastes call. A cache
    miss with live calls off raises ReplayMiss, so the check says "unavailable" and is
    tried live later, never "thin" from the seed show alone."""
    try:
        env = qloo.run(
            "recommend", {"target_type": "tv_show", "signal_location": text, "limit": 10}
        )
    except QlooExecError:
        return None
    if env.status != "ok" or not env.has_results:
        return None
    try:
        return env.entities()[0].entity_id
    except ValidationError:
        return None


def heatmap_cells(qloo: QlooClient, entity_id: str, text: str) -> tuple[Envelope, list]:
    env = qloo.run("where_popular", {"entity": entity_id, "within": text, "limit": HEATMAP_LIMIT})
    return env, env.cells() if env.status != "error" and env.has_results else []


def check_location(qloo: QlooClient, typed: str, seeds: Seeds) -> LocationCheck:
    text = clean(typed)
    if text is None:
        return LocationCheck(
            status="invalid",
            message="Type a neighbourhood or a city, such as “Williamsburg, Brooklyn” or "
            "“Portland, OR”: letters only, no street address or numbers.",
        )
    probe = Location(
        id=location_id(text),
        label=text,
        region="Typed location",
        query=text,
        city=text,
        latitude=0,
        longitude=0,
    )
    unavailable = LocationCheck(
        status="unavailable",
        message="Qloo could not be reached to check this place, and it has not been checked "
        "before. Try again later, or pick one of the preset areas.",
    )
    try:
        probe_id = local_top_show(qloo, text)
        env, cells = heatmap_cells(qloo, probe_id, text) if probe_id else (None, [])
        if env is None or (env.status != "needs_input" and len(cells) < MIN_CELLS):
            # No plain top list, or its top show is thin here: the seed show as well,
            # and the fuller of the two maps decides.
            baseline = resolve_baseline(qloo, probe, seeds.baseline)
            if baseline is None and env is None:
                return unavailable
            if baseline is not None and baseline.id != probe_id:
                seed_env, seed_cells = heatmap_cells(qloo, baseline.id, text)
                if env is None or len(seed_cells) > len(cells):
                    env, cells = seed_env, seed_cells
    except (ReplayMiss, QlooExecError):
        return unavailable

    if env.status == "needs_input":
        # Qloo's candidates carry no region, so only distinct names make useful buttons.
        names = list(dict.fromkeys(c.name for c in env.candidates))
        buttons = [n for n in names if n.lower() != text.lower()][:6]
        if buttons:
            message = f"Qloo knows more than one place matching “{text}”. Pick one:"
        else:
            message = (
                f"Qloo knows several places called “{text}” and cannot tell them apart. "
                "Add the city or state, such as “Springfield, Illinois”."
            )
        return LocationCheck(status="needs_input", message=message, candidates=buttons)
    if env.status == "error":
        return unavailable
    if len(cells) < MIN_CELLS:
        return LocationCheck(
            status="thin",
            message=f"Qloo has too little data for “{text}” ({len(cells)} map cells, fewer "
            f"than {MIN_CELLS}), so a result tuned to it would be weak. Try a larger area, or "
            "add the city, such as “Astoria, Queens”.",
        )
    lats = [c.location.latitude for c in cells]
    lons = [c.location.longitude for c in cells]
    latitude, longitude = sum(lats) / len(lats), sum(lons) / len(lons)
    location = probe.model_copy(
        update={
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "zoom": zoom_for(max(lats) - min(lats), max(lons) - min(lons), latitude),
        }
    )
    return LocationCheck(status="ok", location=location)
