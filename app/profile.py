"""The location profile: what Qloo says about pet interest near one shelter.

Milestone 2 builds it from fixed seed entities (`data/seeds.json`); milestone 3
lets the agent choose them. It is the same for every animal at a location, so
it is computed once and served from the cache.

Everything here is either what Qloo returned or a plain calculation on it
(ranks, lift). Wording for people happens in `app/views/`.
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.locations import Location
from app.qloo.envelope import Envelope
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss

VENUE_LIMIT = 15
HEATMAP_LIMIT = 20
# Version 2: the map combines the top pet titles, and the baseline is the area's own top
# shows instead of one seed show (decision 18). Saved version-1 profiles still load and
# show; app/upgrade_profiles.py brings them up to date.
PROFILE_VERSION = 2
# Each title on the map is one `where_popular` call per area, and the hackathon key is
# refused after about 12 calls in 20 minutes, so two of each.
MAP_TITLES = 2
BASELINE_TITLES = 2
# A top local show whose name or description mentions animals is not a baseline: a word
# list, so the page says "mentions animals", not "is about animals".
PET_WORDS = re.compile(
    r"\b(dogs?|cats?|pupp(y|ies)|kittens?|pets?|animals?|vets?|veterinar\w*|wildlife|zoos?|"
    r"horses?|pon(y|ies)|birds?|whales?|sharks?|tigers?|lions?|bears?|wol(f|ves)|paws?|"
    r"creatures?)\b",
    re.I,
)

# Venue descriptions that rule a place out for an adoption event or flyers.
UNSUITABLE = (
    "adult entertainment",
    "gentlemen",
    "strip club",
    "exotic dancers",
    "hookah",
    "smoke shop",
    "cannabis",
    "dispensary",
    "firearm",
    "gun range",
    "shooting range",
    "nightclub",
    "night club",
)


class Seed(BaseModel):
    name: str
    type: str
    choose: str = ""
    why: str


class Seeds(BaseModel):
    pet: list[Seed]
    # The probe show for checking a typed area (decision 12). Since profile version 2 it
    # is no longer the baseline: the area's own top shows are.
    baseline: Seed


def load_seeds(path: Path) -> Seeds:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Seeds.model_validate({k: v for k, v in data.items() if not k.startswith("_")})


class Entity(BaseModel):
    id: str
    name: str
    type: str
    description: str | None = None
    why: str = ""
    # How the name was settled: "resolved" directly, or "chosen" among candidates.
    resolution: str = "resolved"
    alternatives: int = 0
    # The reason given for the choice among candidates (the agent's, or the seed rule).
    choice_reason: str | None = None


class Venue(BaseModel):
    entity_id: str
    name: str
    address: str | None = None
    neighbourhood: str | None = None
    description: str | None = None
    affinity: float | None = None
    rank: int
    # Whether the baseline's venues were available to compare against.
    compared: bool = False
    baseline_rank: int | None = None
    # Score each pet entity contributed, by entity name (Qloo's explainability).
    contributions: dict[str, float] = Field(default_factory=dict)
    unsuitable: str | None = None
    # The agent's judgement, when an agent built the profile.
    chosen_reason: str | None = None
    rejected_reason: str | None = None

    @property
    def distinctive(self) -> bool:
        """Strong for fans of the pet entities, absent for the baseline's fans."""
        return self.compared and self.baseline_rank is None


class LiftCell(BaseModel):
    geohash: str
    latitude: float
    longitude: float
    # Means over the maps that scored this cell, and how many did.
    pet_score: float
    baseline_score: float | None = None
    pet_count: int = 1
    baseline_count: int = 1

    @property
    def lift(self) -> float | None:
        return None if self.baseline_score is None else self.pet_score - self.baseline_score


class QlooCall(BaseModel):
    """One harness call behind the profile, for the Why panel."""

    operation: str
    purpose: str
    status: str
    results: int


class LocationProfile(BaseModel):
    location_id: str
    species: str | None = None
    # "seeds" for the fixed lookup, "agent" when the agent chose the titles and venues.
    made_by: str = "seeds"
    # Where the titles' order came from: Qloo's `rank`, or the agent when rank failed.
    order_source: str | None = None
    # The titles Qloo ranked for this area, in its order (empty when rank was unavailable).
    ranked: list[str] = Field(default_factory=list)
    # The titles the venues were asked for: the evidence names these, not every title.
    venue_signals: list[str] = Field(default_factory=list)
    pet_entities: list[Entity] = Field(default_factory=list)
    # Version 1's single seed baseline; version 2 leaves it empty and uses `baselines`.
    baseline: Entity | None = None
    # What the pet titles are compared with: the area's top shows ("area"), or the seed
    # show when Qloo's list of them was unusable ("seed").
    baselines: list[Entity] = Field(default_factory=list)
    baseline_source: str = "area"
    # Heatmaps asked for but not returned (a refusal, an error): the map is not finished.
    maps_missing: int = 0
    # The pet titles combined into the map layer.
    map_titles: list[Entity] = Field(default_factory=list)
    version: int = 1
    venues: list[Venue] = Field(default_factory=list)
    # How many venues the baseline's list held, when it was available to compare.
    baseline_venue_count: int | None = None
    cells: list[LiftCell] = Field(default_factory=list)
    # What the area watches in general: the second source for names.
    local_tastes: list[Entity] = Field(default_factory=list)
    calls: list[QlooCall] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Venues, a map, and the comparison behind both: every map arrived and the venues
        were compared. A profile that is not complete is not saved, so the next run asks
        Qloo again for what is missing (the rest comes from the cache)."""
        compared = bool(self.venues) and all(v.compared for v in self.venues)
        lift = any(c.lift is not None for c in self.cells)
        return compared and lift and self.maps_missing == 0


def baseline_titles(profile: LocationProfile) -> list[Entity]:
    """What the pet titles are compared with, for a profile of either version."""
    return profile.baselines or ([profile.baseline] if profile.baseline else [])


def layer_titles(profile: LocationProfile) -> list[Entity]:
    """The pet titles on the map, for a profile of either version."""
    return profile.map_titles or profile.pet_entities[:1]


def baseline_from_tastes(tastes: list[Entity], pets: list[Entity]) -> list[Entity]:
    """The area's top shows as the baseline, leaving out the pet titles themselves and any
    show whose name or description is about animals: comparing a pet show with itself, or
    with another pet show, would hide the very thing the map is for."""
    pet_ids = {e.id for e in pets}
    keep = [
        e
        for e in tastes
        if e.id not in pet_ids and not PET_WORDS.search(f"{e.name} {e.description or ''}")
    ]
    return keep[:BASELINE_TITLES]


def combine_cells(
    pet_maps: list[dict[str, Any]], base_maps: list[dict[str, Any]]
) -> list[LiftCell]:
    """One layer from several heatmaps. Each map's scores are ranks within the area (0 to
    1), so a cell's score is the mean over the maps that scored it; a cell no pet map
    scored is left out, and one no baseline map scored has no lift. Cells keep one
    precision, the most common, so cells of two sizes never overlap."""
    cells: list[LiftCell] = []
    sizes = Counter(len(g) for m in pet_maps for g in m)
    size = sizes.most_common(1)[0][0] if sizes else 0
    geohashes = list(dict.fromkeys(g for m in pet_maps for g in m if len(g) == size))
    for geohash in geohashes:
        pets = [m[geohash] for m in pet_maps if geohash in m]
        bases = [m[geohash] for m in base_maps if geohash in m]
        cells.append(
            LiftCell(
                geohash=geohash,
                latitude=pets[0].location.latitude,
                longitude=pets[0].location.longitude,
                pet_score=sum(c.query.affinity for c in pets) / len(pets),
                baseline_score=(sum(c.query.affinity for c in bases) / len(bases))
                if bases
                else None,
                pet_count=len(pets),
                baseline_count=len(bases),
            )
        )
    return cells


class _Builder:
    def __init__(self, qloo: QlooClient, location: Location):
        self.qloo = qloo
        self.profile = LocationProfile(location_id=location.id)
        self.tastes_ok = False

    def call(self, operation: str, input_: dict[str, Any], purpose: str) -> Envelope | None:
        try:
            env = self.qloo.run(operation, input_)
        except ReplayMiss:
            self.profile.notes.append(f"Not precomputed yet: {purpose}.")
            return None
        except QlooExecError as exc:
            self.profile.notes.append(f"Qloo could not be reached for {purpose}: {exc}")
            return None
        self.profile.calls.append(
            QlooCall(
                operation=operation, purpose=purpose, status=env.status, results=len(env.results)
            )
        )
        if env.status == "error":
            code = env.error.code if env.error else "unknown"
            self.profile.notes.append(f"Qloo returned an error for {purpose} ({code}).")
            return None
        if env.status in ("partial", "degraded"):
            self.profile.notes.extend(
                env.warnings or [f"Qloo's answer for {purpose} is {env.status}."]
            )
        return env

    def resolve(self, seed: Seed) -> Entity | None:
        env = self.call(
            "describe", {"entity": seed.name, "type": seed.type}, f"finding {seed.name} in Qloo"
        )
        if env is None:
            return None
        if env.status == "needs_input":
            matches = [c for c in env.candidates if seed.choose in (c.description or "")]
            if len(matches) != 1:
                self.profile.notes.append(
                    f"{seed.name} is ambiguous in Qloo ({len(env.candidates)} candidates) and the "
                    "seed's rule does not single one out, so it was left out."
                )
                return None
            c = matches[0]
            return Entity(
                id=c.id,
                name=c.name,
                type=c.type,
                description=c.description,
                why=seed.why,
                resolution="chosen",
                alternatives=len(env.candidates) - 1,
            )
        if not env.has_results:
            self.profile.notes.append(f"Qloo has no entity for {seed.name}.")
            return None
        r = env.results[0]
        props = r.get("properties") or {}
        return Entity(
            id=r["entity_id"],
            name=r["name"],
            type=r.get("type", seed.type),
            description=props.get("short_description") or props.get("description"),
            why=seed.why,
        )

    def venues(
        self, signals: list[str], location: Location, purpose: str, *, complete: bool = False
    ) -> list[dict] | None:
        """Venue results, or None. With `complete`, a partial or degraded answer counts as none."""
        env = self.call(
            "recommend",
            {
                "target_type": "place",
                "signals": signals,
                "filter_location": location.query,
                "limit": VENUE_LIMIT,
            },
            purpose,
        )
        if env is None:
            return None
        if not env.has_results:
            self.profile.notes.append(f"Qloo returned no venues for {purpose}.")
            return None
        if complete and env.status != "ok":
            self.profile.notes.append(
                f"Qloo's answer for {purpose} was {env.status}, so it is not used for comparison."
            )
            return None
        return env.results

    def heatmap(self, entity: Entity, location: Location) -> dict[str, Any] | None:
        env = self.call(
            "where_popular",
            {"entity": entity.id, "within": location.query, "limit": HEATMAP_LIMIT},
            f"where fans of {entity.name} are, within {location.label}",
        )
        if env is None:
            return None
        if not env.has_results:
            self.profile.notes.append(f"Qloo returned no map cells for {entity.name}.")
            return None
        return {c.location.geohash: c for c in env.cells()}

    def tastes(self, location: Location, limit: int = 10) -> list[Entity]:
        """The TV shows people around the area tend to like most. `tastes_ok` says whether
        the answer is whole enough to be the baseline: a partial or degraded one may have
        lost the location, and needs_input has no list at all."""
        self.tastes_ok = False
        env = self.call(
            "recommend",
            {"target_type": "tv_show", "signal_location": location.query, "limit": limit},
            f"TV shows people around {location.label} tend to like",
        )
        if env is None:
            return []
        if env.status == "needs_input":
            self.profile.notes.append(
                f"Qloo could not tell which place {location.query!r} means for the area's "
                "top shows."
            )
            return []
        if not env.has_results:
            return []
        self.tastes_ok = env.status == "ok"
        return [
            Entity(
                id=r["entity_id"],
                name=r["name"],
                type=r.get("type", "urn:entity:tv_show"),
                description=(r.get("properties") or {}).get("short_description")
                or (r.get("properties") or {}).get("description"),
            )
            for r in env.results
        ]


def screen(description: str | None) -> str | None:
    """Why a venue is unsuitable for an adoption event, or None."""
    text = (description or "").lower()
    return next((word for word in UNSUITABLE if word in text), None)


def rank_band(rank: int, total: int) -> str:
    """Where a place sits in Qloo's list, best first: 'top', 'middle' or 'bottom' third."""
    third = -(-total // 3)
    if rank <= third:
        return "top"
    return "bottom" if rank > total - third else "middle"


def build_profile(qloo: QlooClient, location: Location, seeds: Seeds) -> LocationProfile:
    """The fixed lookup: seed titles, resolved by name, then the shared assembly."""
    b = _Builder(qloo, location)
    pets = [e for e in (b.resolve(s) for s in seeds.pet) if e is not None]
    tastes, baselines, source = area_baseline(b, location, seeds, pets) if pets else ([], [], "")
    profile = assemble_profile(b, location, pets, baselines)
    profile.local_tastes, profile.baseline_source = tastes, source or "area"
    return profile


def area_baseline(
    b: "_Builder", location: Location, seeds: Seeds, pets: list[Entity]
) -> tuple[list[Entity], list[Entity], str]:
    """The area's top shows and the baseline from them (decision 18): (tastes, baselines,
    source). When Qloo's list is unusable, or every top show mentions animals, the seed
    show stands in, and a note says so."""
    tastes = b.tastes(location)
    baselines = baseline_from_tastes(tastes, pets) if b.tastes_ok else []
    if baselines:
        return tastes, baselines, "area"
    seed = b.resolve(seeds.baseline)
    if seed is None:
        return tastes, [], "seed"
    b.profile.notes.append(
        f"Qloo's list of the shows people around {location.label} watch most could not be "
        f"used, so the comparison is with one widely watched show unrelated to pets, "
        f"{seed.name}."
    )
    return tastes, [seed], "seed"


def baseline_for(
    qloo: QlooClient, location: Location, seeds: Seeds
) -> tuple[list[Entity], list[Entity], str, list[str]]:
    """`area_baseline` before any pet title is known (the agent's run), with its notes."""
    b = _Builder(qloo, location)
    tastes, baselines, source = area_baseline(b, location, seeds, [])
    return tastes, baselines, source, b.profile.notes


def resolve_baseline(qloo: QlooClient, location: Location, seed: Seed) -> Entity | None:
    """The probe show on its own, for checking a typed area (decision 12)."""
    return _Builder(qloo, location).resolve(seed)


def assemble_profile(
    b: "_Builder",
    location: Location,
    pets: list[Entity],
    baselines: list[Entity],
    venue_signals: list[str] | None = None,
) -> LocationProfile:
    """Venues for the pet titles and the baseline shows, compared, and the lift map.

    `venue_signals` are the titles the venues are asked for, when not all of
    `pets` (an agent asks for venues with its top few). Same input, same cache key.
    """
    p = b.profile
    p.version = PROFILE_VERSION
    p.pet_entities = pets
    p.baselines = baselines
    if not p.pet_entities:
        p.notes.append("No pet-themed entity could be resolved, so there is nothing to look up.")
        return p

    pet_names = {e.id: e.name for e in p.pet_entities}
    p.venue_signals = venue_signals or list(pet_names)
    pet_venues = b.venues(
        p.venue_signals,
        location,
        f"venues near {location.label} for fans of pet-themed titles",
    )
    base_venues = None
    if p.baselines:
        # An incomplete baseline would make missing venues look distinctive.
        base_venues = b.venues(
            [e.id for e in p.baselines],
            location,
            f"venues near {location.label} for fans of the area's top shows",
            complete=True,
        )
    if base_venues is not None:
        p.baseline_venue_count = len(base_venues)
    baseline_ranks = {r["entity_id"]: i for i, r in enumerate(base_venues or [], start=1)}

    for rank, r in enumerate(pet_venues or [], start=1):
        props = r.get("properties") or {}
        explained = (r.get("explainability") or {}).get("signal.interests.entities") or []
        description = props.get("short_description") or props.get("description")
        p.venues.append(
            Venue(
                entity_id=r["entity_id"],
                name=r["name"],
                address=props.get("address"),
                neighbourhood=(props.get("geocode") or {}).get("name"),
                description=description,
                affinity=r.get("affinity"),
                rank=rank,
                compared=base_venues is not None,
                baseline_rank=baseline_ranks.get(r["entity_id"]),
                contributions={
                    pet_names[x["entity_id"]]: x["score"]
                    for x in explained
                    if x.get("entity_id") in pet_names
                },
                unsuitable=screen(description),
            )
        )
    if pet_venues and base_venues is None:
        p.notes.append("Without the baseline's venues, no venue can be marked as distinctive.")

    # The map: the titles the venues were asked for first, then the rest, two of them.
    by_id = {e.id: e for e in p.pet_entities}
    ordered = [by_id[i] for i in p.venue_signals if i in by_id] + p.pet_entities
    p.map_titles = list({e.id: e for e in ordered}.values())[:MAP_TITLES]
    pet_maps = [m for m in (b.heatmap(e, location) for e in p.map_titles) if m]
    base_maps = [m for m in (b.heatmap(e, location) for e in p.baselines) if m]
    p.maps_missing = len(p.map_titles) + len(p.baselines) - len(pet_maps) - len(base_maps)
    p.cells = combine_cells(pet_maps, base_maps)
    return p


def profile_from(
    qloo: QlooClient,
    location: Location,
    pets: list[Entity],
    baselines: list[Entity],
    venue_signals: list[str] | None = None,
) -> LocationProfile:
    """Assemble a profile around titles chosen elsewhere (by the agent)."""
    return assemble_profile(_Builder(qloo, location), location, pets, baselines, venue_signals)


def baseline_venue_ids(
    qloo: QlooClient, location: Location, baselines: list[Entity]
) -> list[str] | None:
    """The baseline shows' venues in rank order, or None when there is no complete answer."""
    b = _Builder(qloo, location)
    results = b.venues(
        [e.id for e in baselines],
        location,
        f"venues near {location.label} for fans of the area's top shows",
        complete=True,
    )
    return None if results is None else [r["entity_id"] for r in results]


def local_tastes(qloo: QlooClient, location: Location) -> list[Entity]:
    """What the area watches in general: the second source for names, and the baseline."""
    return _Builder(qloo, location).tastes(location)
