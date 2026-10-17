"""The location profile: what Qloo says about pet interest near one shelter.

Milestone 2 builds it from fixed seed entities (`data/seeds.json`); milestone 3
lets the agent choose them. It is the same for every animal at a location, so
it is computed once and served from the cache.

Everything here is either what Qloo returned or a plain calculation on it
(ranks, lift). Wording for people happens in `app/views/`.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.locations import Location
from app.qloo.envelope import Envelope
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss

VENUE_LIMIT = 15
HEATMAP_LIMIT = 20

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
    pet_score: float
    baseline_score: float | None = None

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
    baseline: Entity | None = None
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
        return bool(self.venues) and bool(self.cells)


class _Builder:
    def __init__(self, qloo: QlooClient, location: Location):
        self.qloo = qloo
        self.profile = LocationProfile(location_id=location.id)

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
    baseline = b.resolve(seeds.baseline)
    return assemble_profile(b, location, pets, baseline)


def resolve_baseline(qloo: QlooClient, location: Location, seed: Seed) -> Entity | None:
    """The baseline title on its own, for an agent-built profile."""
    return _Builder(qloo, location).resolve(seed)


def assemble_profile(
    b: "_Builder",
    location: Location,
    pets: list[Entity],
    baseline: Entity | None,
    venue_signals: list[str] | None = None,
) -> LocationProfile:
    """Venues for the pet titles and the baseline, compared, and the lift map.

    `venue_signals` are the titles the venues are asked for, when not all of
    `pets` (an agent asks for venues with its top few). Same input, same cache key.
    """
    p = b.profile
    p.pet_entities = pets
    p.baseline = baseline
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
    if p.baseline is not None:
        # An incomplete baseline would make missing venues look distinctive.
        base_venues = b.venues(
            [p.baseline.id],
            location,
            f"venues near {location.label} for the baseline show",
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

    pet_cells = b.heatmap(p.pet_entities[0], location)
    base_cells = b.heatmap(p.baseline, location) if p.baseline is not None else None
    for geohash, cell in (pet_cells or {}).items():
        base = (base_cells or {}).get(geohash)
        p.cells.append(
            LiftCell(
                geohash=geohash,
                latitude=cell.location.latitude,
                longitude=cell.location.longitude,
                pet_score=cell.query.affinity,
                baseline_score=base.query.affinity if base else None,
            )
        )
    return p


def profile_from(
    qloo: QlooClient,
    location: Location,
    pets: list[Entity],
    baseline: Entity | None,
    venue_signals: list[str] | None = None,
) -> LocationProfile:
    """Assemble a profile around titles chosen elsewhere (by the agent)."""
    return assemble_profile(_Builder(qloo, location), location, pets, baseline, venue_signals)


def baseline_venue_ids(qloo: QlooClient, location: Location, baseline: Entity) -> list[str] | None:
    """The baseline's venues in rank order, or None when there is no complete answer."""
    b = _Builder(qloo, location)
    results = b.venues(
        [baseline.id],
        location,
        f"venues near {location.label} for the baseline show",
        complete=True,
    )
    return None if results is None else [r["entity_id"] for r in results]


def local_tastes(qloo: QlooClient, location: Location, limit: int = 10) -> list[Entity]:
    """What the area watches in general, the second source for names."""
    b = _Builder(qloo, location)
    env = b.call(
        "recommend",
        {"target_type": "tv_show", "signal_location": location.query, "limit": limit},
        f"TV shows people around {location.label} tend to like",
    )
    if env is None or not env.has_results:
        return []
    return [
        Entity(
            id=r["entity_id"],
            name=r["name"],
            type=r.get("type", "urn:entity:tv_show"),
            description=(r.get("properties") or {}).get("short_description"),
        )
        for r in env.results
    ]
