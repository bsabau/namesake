"""A fake Qloo client and hand-made envelopes for profile and view tests.

Every ID uses the synthetic prefix and every name is invented, so nothing here
is Qloo data. The fake answers by operation and input; anything not scripted
raises ReplayMiss, as replay mode would.
"""

from typing import Any

from app.locations import Location
from app.profile import Seed, Seeds
from app.qloo.cache import canonical
from app.qloo.envelope import Envelope
from app.qloo.exec import ReplayMiss

DOG_SHOW = "00000000-0000-4000-8000-000000000101"
DOG_SHOW_OLD = "00000000-0000-4000-8000-000000000102"
CAT_SHOW = "00000000-0000-4000-8000-000000000103"
BASELINE = "00000000-0000-4000-8000-000000000104"
# The area's other top shows: a second baseline, a pet-themed one the baseline leaves out,
# and one beyond the two the baseline takes.
BASELINE_2 = "00000000-0000-4000-8000-000000000107"
LOCAL_PET_SHOW = "00000000-0000-4000-8000-000000000108"
LOCAL_QUIZ = "00000000-0000-4000-8000-000000000109"


def venue_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{200 + n:012d}"


LOCATION = Location(
    id="example",
    label="Example Slope",
    region="Example City",
    query="Example Slope, Example City",
    city="New York City",
    latitude=40.672,
    longitude=-73.978,
    zoom=14,
    community_channel="example-language noticeboards in a nearby neighbourhood",
)

SEEDS = Seeds(
    pet=[
        Seed(name="Example Dog Show", type="tv_show", choose="2018", why="a show about dogs"),
        Seed(name="Example Cat Show", type="tv_show", why="a show about cats"),
    ],
    baseline=Seed(name="Example Drama", type="tv_show", why="a drama with no pets"),
)


def envelope(operation: str, status: str = "ok", **fields) -> Envelope:
    return Envelope.parse({"operation": operation, "status": status, **fields})


def describe_needs_input() -> Envelope:
    return envelope(
        "describe",
        "needs_input",
        resolution={
            "issues": [
                {
                    "input": "Example Dog Show",
                    "kind": "ambiguous",
                    "candidates": [
                        {
                            "id": DOG_SHOW,
                            "name": "Example Dog Show",
                            "type": "urn:entity:tv_show",
                            "description": "Example Dog Show (2018) is a made-up series.",
                        },
                        {
                            "id": DOG_SHOW_OLD,
                            "name": "Example Dog Show",
                            "type": "urn:entity:tv_show",
                            "description": "Example Dog Show (1976) is a different made-up series.",
                        },
                    ],
                }
            ]
        },
    )


def describe_ok(entity_id: str, name: str) -> Envelope:
    return envelope(
        "describe",
        results=[{"entity_id": entity_id, "name": name, "type": "urn:entity:tv_show"}],
    )


def venue(n: int, name: str, description: str, contributions: dict[str, float]) -> dict:
    return {
        "entity_id": venue_id(n),
        "name": name,
        "type": "urn:entity:place",
        "affinity": 0.7 - n / 100,
        "properties": {
            "address": f"{n} Example St",
            "geocode": {"name": "Example Slope"},
            "short_description": description,
        },
        "explainability": {
            "signal.interests.entities": [
                {"entity_id": k, "score": v} for k, v in contributions.items()
            ]
        },
    }


PET_VENUES = [
    venue(1, "Busy Arena", "A large arena.", {DOG_SHOW: 1.0, CAT_SHOW: 0.5}),
    venue(2, "Hookah Corner", "A hookah lounge.", {DOG_SHOW: 1.0}),
    venue(3, "Community Hall", "A neighbourhood arts centre.", {DOG_SHOW: 0.8, CAT_SHOW: 1.0}),
    venue(4, "Garden Cafe", "A cafe with a garden.", {CAT_SHOW: 1.0}),
]
BASELINE_VENUES = [
    venue(1, "Busy Arena", "A large arena.", {BASELINE: 1.0}),
    venue(5, "Sports Bar", "A sports bar.", {BASELINE_2: 1.0}),
]


def show(entity_id: str, name: str, description: str) -> dict:
    return {
        "entity_id": entity_id,
        "name": name,
        "type": "urn:entity:tv_show",
        "properties": {"short_description": description},
    }


# What the area watches most, in Qloo's order.
LOCAL_SHOWS = [
    show(LOCAL_PET_SHOW, "Example Puppy Club", "A made-up series about a puppy training club."),
    show(BASELINE, "Example Drama", "A made-up drama about a ranch."),
    show(BASELINE_2, "Example Comedy", "A made-up office comedy."),
    show(LOCAL_QUIZ, "Example Quiz", "A made-up quiz show."),
]


def cell(geohash: str, lat: float, lon: float, affinity: float) -> dict:
    return {
        "location": {"latitude": lat, "longitude": lon, "geohash": geohash},
        "query": {"affinity": affinity, "popularity": 0.5},
    }


PET_CELLS = [cell("dr5rks5", 40.6721, -73.9771, 0.9), cell("dr5rk66", 40.6625, -73.9895, 0.6)]
CAT_CELLS = [cell("dr5rks5", 40.6721, -73.9771, 0.7)]
BASELINE_CELLS = [cell("dr5rks5", 40.6721, -73.9771, 0.4)]
BASELINE_2_CELLS = [cell("dr5rks5", 40.6721, -73.9771, 0.2)]


def standard_script() -> dict[tuple[str, str], Envelope]:
    """Every call a complete profile for LOCATION makes, with its answer."""
    q = LOCATION.query
    return {
        key("describe", {"entity": "Example Dog Show", "type": "tv_show"}): describe_needs_input(),
        key("describe", {"entity": "Example Cat Show", "type": "tv_show"}): describe_ok(
            CAT_SHOW, "Example Cat Show"
        ),
        key("describe", {"entity": "Example Drama", "type": "tv_show"}): describe_ok(
            BASELINE, "Example Drama"
        ),
        key(
            "recommend",
            {
                "target_type": "place",
                "signals": [DOG_SHOW, CAT_SHOW],
                "filter_location": q,
                "limit": 15,
            },
        ): envelope("recommend", results=PET_VENUES),
        key("recommend", {"target_type": "tv_show", "signal_location": q, "limit": 10}): envelope(
            "recommend", results=LOCAL_SHOWS
        ),
        key(
            "recommend",
            {
                "target_type": "place",
                "signals": [BASELINE, BASELINE_2],
                "filter_location": q,
                "limit": 15,
            },
        ): envelope("recommend", results=BASELINE_VENUES),
        key("where_popular", {"entity": DOG_SHOW, "within": q, "limit": 20}): envelope(
            "where_popular", results=PET_CELLS
        ),
        key("where_popular", {"entity": CAT_SHOW, "within": q, "limit": 20}): envelope(
            "where_popular", results=CAT_CELLS
        ),
        key("where_popular", {"entity": BASELINE, "within": q, "limit": 20}): envelope(
            "where_popular", results=BASELINE_CELLS
        ),
        key("where_popular", {"entity": BASELINE_2, "within": q, "limit": 20}): envelope(
            "where_popular", results=BASELINE_2_CELLS
        ),
    }


def key(operation: str, input_: dict[str, Any]) -> tuple[str, str]:
    return operation, canonical(input_)


class FakeQloo:
    def __init__(self, script: dict[tuple[str, str], Envelope]):
        self.script = script
        self.calls: list[tuple[str, dict]] = []

    def run(self, operation: str, input_: dict[str, Any]) -> Envelope:
        self.calls.append((operation, input_))
        try:
            return self.script[key(operation, input_)]
        except KeyError:
            raise ReplayMiss(f"not scripted: {operation} {input_}") from None
