"""Milestone 1 probes: what Qloo can say about pet interest near a shelter.

Replays from `var/qloo-recordings/` by default and spends no quota:

    uv run python scripts/probe_m1.py            # replay; a missing recording is reported
    uv run python scripts/probe_m1.py --live     # call Qloo for anything not yet recorded

Real Qloo IDs may not be committed, so every ID is picked at run time from an
earlier response (by name, or by a phrase in Qloo's description), the same way
the agent will pick them. The answers are written up in `docs/qloo-findings.md`.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.qloo.cache import Cache  # noqa: E402
from app.qloo.envelope import Candidate, Envelope  # noqa: E402
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss, harness_env  # noqa: E402
from app.qloo.geohash import decode, haversine_km, nearest, within  # noqa: E402

RECORDINGS = get_settings().qloo_recordings
PARK_SLOPE = "Park Slope, Brooklyn"
ASTORIA = "Astoria, Queens"
AUSTIN = "Austin, TX"
SHELTERS = {PARK_SLOPE: (40.672, -73.978), ASTORIA: (40.764, -73.923)}

PET_MEDIA_TAGS = [
    "urn:tag:genre:media:dogs",
    "urn:tag:keyword:media:pet_dogs",
    "urn:tag:subgenre:qloo:pets",
    "urn:tag:keyword:qloo:cats",
]
PET_LIFESTYLE_TAGS = [
    "urn:tag:lifestyle:qloo:dog_ownership",
    "urn:tag:lifestyle:qloo:pet_ownership",
]

# Ten pet-themed series, as a volunteer or the agent would name them.
PET_SHOWS = [
    "Bluey",
    "Clifford the Big Red Dog",
    "My Cat from Hell",
    "Puppy Dog Pals",
    "Dog with a Blog",
    "Dog Whisperer with Cesar Millan",
    "PAW Patrol",
    "Pound Puppies",
    "Lassie",
    "Too Cute",
]
# How each ambiguous name is settled: a phrase that must appear in Qloo's description.
CHOICE = {
    "Bluey": "2018",
    "Clifford the Big Red Dog": "2019",
    "PAW Patrol": "2013",
    "Pound Puppies": "2010",
    "Lassie": "1954",
    "Too Cute": "Animal Planet",
}


def legacy(name: str) -> Envelope | None:
    """A recording made before the wrapper existed, stored as a bare envelope.

    These hold the seed entities for later probes. They are private, so a fresh
    clone has none, and the probes that need them are skipped.
    """
    path = RECORDINGS / f"{name}.json"
    if not path.is_file():
        return None
    return Envelope.parse(json.loads(path.read_text(encoding="utf-8")))


def pick(candidates: list[Candidate], name: str, phrase: str) -> Candidate:
    matches = [c for c in candidates if c.name.startswith(name) and phrase in (c.description or "")]
    if len(matches) != 1:
        raise LookupError(f"{name!r} with {phrase!r}: {len(matches)} candidates match")
    return matches[0]


class Probes:
    def __init__(self, qloo: QlooClient):
        self.qloo = qloo
        self.missing: list[str] = []

    def run(self, label: str, operation: str, input_: dict) -> Envelope | None:
        try:
            env = self.qloo.run(operation, input_)
        except (ReplayMiss, QlooExecError) as exc:
            self.missing.append(label)
            print(f"\n## {label}\n   not available: {exc}")
            return None
        print(f"\n## {label}\n   status={env.status} results={len(env.results)}")
        if env.error:
            print(f"   error={env.error.code} retryable={env.error.retryable}")
            self.missing.append(label)
            return None
        return env


def names(env: Envelope | None, n: int = 15) -> list[str]:
    return [e.name for e in env.entities()[:n]] if env and env.has_results else []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call Qloo for unrecorded probes")
    args = parser.parse_args()
    settings = get_settings()
    qloo = QlooClient(
        Cache(settings.cache_db),
        mode="live" if args.live else "replay",
        recordings=RECORDINGS,
        env=harness_env(settings),
        min_interval=settings.qloo_min_interval,
    )
    p = Probes(qloo)

    # P1. Pet tags exist, in media, lifestyle and place-category families.
    for query in ["dogs", "cats", "pets"]:
        env = p.run(f"P1 find_tags {query}", "find_tags", {"query": query, "limit": 10})
        if env:
            for tag in env.results:
                print(f"   {tag['id']}")

    # P2. Filtering TV and films to pet tags, per location.
    for loc in [PARK_SLOPE, ASTORIA, AUSTIN]:
        env = p.run(
            f"P2 pet-tagged TV, {loc}",
            "recommend",
            {
                "target_type": "tv_show",
                "include_tags": PET_MEDIA_TAGS,
                "include_tags_operator": "union",
                "signal_location": loc,
                "limit": 15,
            },
        )
        print(f"   {names(env)}")
    env = p.run(
        f"P2 pet-tagged films, {PARK_SLOPE}",
        "recommend",
        {
            "target_type": "movie",
            "include_tags": PET_MEDIA_TAGS,
            "include_tags_operator": "union",
            "signal_location": PARK_SLOPE,
            "limit": 15,
        },
    )
    print(f"   {names(env)}")

    # P3. Venues near the shelter: a lifestyle-tag signal, pet-show signals, and a baseline.
    tagged = p.run(
        f"P3 venues, pet-owner tags, {PARK_SLOPE}",
        "recommend",
        {
            "target_type": "place",
            "signal_tags": PET_LIFESTYLE_TAGS,
            "signal_tags_operator": "union",
            "filter_location": PARK_SLOPE,
            "limit": 15,
        },
    )
    if tagged:
        print(f"   distinct affinities: {sorted({e.affinity for e in tagged.entities()})}")

    seeds = seed_entities(p)
    if seeds is None:
        print("\n## P3, P6 and the citywide comparison skipped: seed recordings are missing")
    else:
        venue_and_heatmap_probes(p, *seeds)

    rank_probes(p)
    print(f"\nlive calls this run: {qloo.live_calls}; not available: {p.missing or 'none'}")


def seed_entities(p: Probes):
    """Bluey, Yellowstone and My Cat from Hell, from earlier recordings, or None."""
    bluey_env = legacy("where_popular__bluey__nyc")
    yellowstone_env = legacy("where_popular__yellowstone__nyc")
    pet_tv = p.qloo.cache.get(
        "recommend",
        {
            "target_type": "tv_show",
            "include_tags": PET_MEDIA_TAGS,
            "include_tags_operator": "union",
            "signal_location": PARK_SLOPE,
            "limit": 15,
        },
    )
    if bluey_env is None or yellowstone_env is None or pet_tv is None:
        return None
    cat_show = next(
        (e for e in Envelope.parse(pet_tv).entities() if e.name == "My Cat from Hell"), None
    )
    if cat_show is None:
        return None
    return (
        bluey_env.interpretation["entity"],
        yellowstone_env.interpretation["entity"],
        cat_show,
    )


def venue_and_heatmap_probes(p: Probes, bluey: dict, yellowstone: dict, cat_show) -> None:
    venues = {}
    for label, signals in [
        ("pet shows", [bluey["entityId"], cat_show.entity_id]),
        ("baseline show", [yellowstone["entityId"]]),
    ]:
        env = p.run(
            f"P3 venues, {label}, {PARK_SLOPE}",
            "recommend",
            {
                "target_type": "place",
                "signals": signals,
                "filter_location": PARK_SLOPE,
                "limit": 15,
            },
        )
        venues[label] = names(env)
        if env and env.has_results:
            affs = [e.affinity for e in env.entities()]
            print(f"   affinity {min(affs):.3f}-{max(affs):.3f}: {venues[label]}")
    if all(venues.values()):
        shared = set(venues["pet shows"]) & set(venues["baseline show"])
        only_pet = [v for v in venues["pet shows"] if v not in shared]
        print(f"   shared with baseline: {len(shared)}/15; only with pet shows: {only_pet}")
    env = p.run(
        f"P3 venues, pet shows, {ASTORIA}",
        "recommend",
        {
            "target_type": "place",
            "signals": [bluey["entityId"], cat_show.entity_id],
            "filter_location": ASTORIA,
            "limit": 15,
        },
    )
    print(f"   {names(env)}")

    # P6. Heatmaps inside the neighbourhood, pet show against a baseline show.
    local = {}
    for label, entity in [("Bluey", bluey), ("baseline Yellowstone", yellowstone)]:
        env = p.run(
            f"P6 heatmap within {PARK_SLOPE}, {label}",
            "where_popular",
            {"entity": entity["entityId"], "within": PARK_SLOPE, "limit": 20},
        )
        if env and env.has_results:
            cells = env.cells()
            local[label] = {c.location.geohash: c.query.affinity for c in cells}
            affs = [c.query.affinity for c in cells]
            sizes = sorted({len(c.location.geohash) for c in cells})
            span = f"{min(affs):.3f}-{max(affs):.3f}"
            print(f"   {len(cells)} cells, geohash length {sizes}, affinity {span}")
    if len(local) == 2:
        pet, base = local["Bluey"], local["baseline Yellowstone"]
        shared = sorted(set(pet) & set(base), key=lambda g: base[g] - pet[g])
        print(f"   cells in both: {len(shared)}; only Bluey: {len(set(pet) - set(base))}")
        lat, lon = SHELTERS[PARK_SLOPE]
        for g in shared:
            km = haversine_km(lat, lon, *decode(g))
            print(f"   {g}  lift {pet[g] - base[g]:+.3f}  ({km:.1f} km from the shelter)")

    # Offline: how close do citywide top-20 heatmap cells come to each shelter?
    print("\n## Citywide heatmaps near the shelters (recorded earlier)")
    for name in ["bluey", "yellowstone", "the-other-two", "mets", "yankees"]:
        env = legacy(f"where_popular__{name}__nyc")
        if env is None:
            continue
        cells = env.cells()
        parts = []
        for loc, (lat, lon) in SHELTERS.items():
            c = nearest(cells, lat, lon)
            km = haversine_km(lat, lon, c.location.latitude, c.location.longitude)
            near = len(within(cells, lat, lon, 3))
            parts.append(f"{loc.split(',')[0]}: nearest {km:.1f} km, {near} within 3 km")
        print(f"   {name:14} " + " | ".join(parts))


def rank_probes(p: Probes) -> None:
    # P4. Ranking pet shows by name: ambiguous names come back as candidates.
    rank_by_name = {}
    for loc in [PARK_SLOPE, ASTORIA]:
        env = p.run(
            f"P4 rank pet shows by name, {loc}",
            "rank",
            {"option_type": "tv_show", "options": PET_SHOWS, "signal_location": loc},
        )
        if env:
            rank_by_name[loc] = env
            print(f"   ambiguous: {sorted({c.name for c in env.candidates})}")

    # P5. The same ranking with each ambiguous name settled by its description.
    if rank_by_name:
        candidates = next(iter(rank_by_name.values())).candidates
        options = [pick(candidates, n, CHOICE[n]).id if n in CHOICE else n for n in PET_SHOWS]
        for loc in [PARK_SLOPE, ASTORIA]:
            env = p.run(
                f"P5 rank resolved pet shows, {loc}",
                "rank",
                {"option_type": "tv_show", "options": options, "signal_location": loc},
            )
            print(f"   {names(env)}")


if __name__ == "__main__":
    main()
