"""Geohash helpers for the six-character cells that `where_popular` returns.

Pure Python, no new dependencies: the app only needs a cell's edges, centre and
distance, never a fresh encode.
"""

import math
from collections.abc import Iterator

from app.qloo.envelope import HeatmapCell

ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"
_VALUES = {char: value for value, char in enumerate(ALPHABET)}
EARTH_RADIUS_KM = 6371.0088


def _checked(geohash: str) -> str:
    text = geohash.lower()
    if not text:
        raise ValueError("geohash is empty")
    for char in text:
        if char not in _VALUES:
            raise ValueError(f"invalid geohash character {char!r}")
    return text


def bounds(geohash: str) -> tuple[float, float, float, float]:
    """The cell's edges, as (south, west, north, east) in degrees."""
    south, north = -90.0, 90.0
    west, east = -180.0, 180.0
    longitude_bit = True
    for char in _checked(geohash):
        value = _VALUES[char]
        for shift in range(4, -1, -1):
            bit = (value >> shift) & 1
            if longitude_bit:
                middle = (west + east) / 2
                if bit:
                    west = middle
                else:
                    east = middle
            else:
                middle = (south + north) / 2
                if bit:
                    south = middle
                else:
                    north = middle
            longitude_bit = not longitude_bit
    return south, west, north, east


def decode(geohash: str) -> tuple[float, float]:
    """The cell's centre, as (latitude, longitude) in degrees."""
    south, west, north, east = bounds(geohash)
    return (south + north) / 2, (west + east) / 2


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _distance_from(
    cells: list[HeatmapCell], latitude: float, longitude: float
) -> Iterator[tuple[float, HeatmapCell]]:
    for cell in cells:
        yield (
            haversine_km(latitude, longitude, cell.location.latitude, cell.location.longitude),
            cell,
        )


def nearest(cells: list[HeatmapCell], latitude: float, longitude: float) -> HeatmapCell | None:
    """The cell whose centre is closest to the point, or `None` for an empty list."""
    if not cells:
        return None
    return min(
        cells,
        key=lambda cell: haversine_km(
            latitude, longitude, cell.location.latitude, cell.location.longitude
        ),
    )


def within(
    cells: list[HeatmapCell], latitude: float, longitude: float, km: float
) -> list[HeatmapCell]:
    """The cells no further than `km` from the point, nearest first."""
    ordered = sorted(_distance_from(cells, latitude, longitude), key=lambda pair: pair[0])
    return [cell for distance, cell in ordered if distance <= km]
