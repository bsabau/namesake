"""The location profile: what Qloo says about pet interest near one shelter.

Milestone 2 builds it from fixed seed entities (`data/seeds.json`); milestone 3
lets the agent choose them. It is the same for every animal at a location, so
it is computed once and served from the cache.

Everything here is either what Qloo returned or a plain calculation on it
(ranks, lift). Wording for people happens in `app/views/`.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

from app.agent.checks import mentions_identity
from app.locations import Location
from app.qloo.envelope import Envelope
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss

VENUE_LIMIT = 15
# The kinds of place Qloo is asked for (decided 18 October), in groups, each with the
# reason it is in: places that can host an adoption stand or take a flyer, open to
# everyone. Without them Qloo's list near a spot is mostly what is popular there (an arena,
# an archery range, axe throwing), whatever the titles. Category IDs are Qloo's, checked
# with find_tags; at most ten in all, the harness's limit.
VENUE_GROUPS = [
    (
        "cafes and breweries",
        ("cafe", "coffee_shop", "brewery"),
        "people linger, and many host local events",
    ),
    (
        "bookshops and pet shops",
        ("book_store", "pet_store", "pet_supply_store"),
        "they take a flyer; pet shops reach pet owners",
    ),
    (
        "community places",
        ("community_center", "library", "park", "art_center"),
        "centres, libraries, parks: open to everyone",
    ),
]
# The groups left out, each with its reason; the page names them too.
LEFT_OUT_GROUPS = [
    ("arenas and stadiums", "ticketed"),
    ("bars and clubs", "not for all ages"),
    ("gyms", "members only"),
    ("restaurants and hotels", "no room for a stand"),
]
CATEGORY_TAGS = [f"urn:tag:category:place:{c}" for _, cs, _ in VENUE_GROUPS for c in cs]
# A full answer with fewer places than this in those kinds and an area's venues are asked
# for places of any kind.
MIN_CATEGORY_VENUES = 5


def venue_input(signals: list[str], location: Location, filtered: bool) -> dict[str, Any]:
    """The one venue request, so the agent's tool and the assembly share a cache key."""
    request: dict[str, Any] = {
        "target_type": "place",
        "signals": signals,
        "filter_location": location.query,
        "limit": VENUE_LIMIT,
    }
    if filtered:
        request |= {"include_tags": CATEGORY_TAGS, "include_tags_operator": "union"}
    return request


def too_few(env: Envelope | None) -> bool:
    """A full answer (ok, or empty) with fewer than MIN_CATEGORY_VENUES places: only that
    shows an area has too few of these kinds. A failed, partial, degraded or ambiguous
    answer decides nothing."""
    return (
        env is not None
        and env.status in ("ok", "empty")
        and len(env.results or []) < MIN_CATEGORY_VENUES
    )


HEATMAP_LIMIT = 20
# Version 2: the map combines the top pet titles, and the baseline is the area's own top
# shows instead of one seed show (decision 18). Saved version-1 profiles still load and
# show; app/upgrade_profiles.py brings them up to date.
PROFILE_VERSION = 3
# Each title on the map is one `where_popular` call per area, and the hackathon key is
# refused after about 12 calls in 20 minutes, so two of each.
MAP_TITLES = 2
# A first map title with fewer cells than this within the area is swapped, once, for the
# next pet title when that gives a better map (PAW Patrol had 1 cell in Hoboken, 18
# October). The same bar accepts a typed area (custom_location.MIN_CELLS). Version 3
# profiles have had this check.
THIN_MAP = 5
# Said once when Qloo cannot tell which place a heatmap means (needs_input).
PLACE_NOTE = "Qloo could not tell which place {query!r} means for its maps."
BASELINE_TITLES = 2
# A top local show whose name or description mentions animals is not a baseline: a word
# list, so the page says "mentions animals", not "is about animals".
# Plain animal words only: "The Bear" or "Shark Tank" must not lose the area a baseline.
PET_WORDS = re.compile(
    r"\b(dogs?|cats?|pupp(y|ies)|kittens?|pets?|animals?|vets?|veterinar\w*|wildlife|zoos?|"
    r"horses?|pon(y|ies))\b",
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
    # The fallback probe for checking a typed area, after the area's own top show
    # (decision 12). Since profile version 2 it is no longer the baseline.
    baseline: Seed


def load_seeds(path: Path) -> Seeds:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Seeds.model_validate({k: v for k, v in data.items() if not k.startswith("_")})


class PetVerdict(BaseModel):
    """A classifier's answers for one title (app/classify.py): each the probability that
    the answer is yes."""

    pets: float
    dogs: float
    cats: float
    family: float
    real_people: float
    model: str = ""


# Qloo's pet media tags (milestone 1). As filters they left almost nothing; as signals
# with the area, they give each area its own list of pet-themed titles (decision 22).
PET_TAGS = [
    "urn:tag:genre:media:dogs",
    "urn:tag:keyword:media:pet_dogs",
    "urn:tag:subgenre:qloo:pets",
    "urn:tag:keyword:qloo:cats",
]


def entity_type(raw: str | None, kind: str) -> str:
    """Qloo's type for a result, or the kind that was asked for when the answer gives only
    the generic "urn:entity" (its `recommend` lists do)."""
    return raw if raw and raw.startswith("urn:entity:") else f"urn:entity:{kind}"


class FoundIn(BaseModel):
    """Where Qloo listed a title the AI did not propose itself: among the titles people
    around the area who like `signal` also like (decision 20), or, with `by_tags`, among
    the pet-themed titles people around the area tend to like (decision 22)."""

    signal: str
    kind: str
    position: int
    out_of: int
    by_tags: bool = False


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
    # For a title found in Qloo's list for the area (decision 20): where, and how the
    # classifier sorted it (None when the classifier was off or failed).
    found_in: FoundIn | None = None
    verdict: PetVerdict | None = None
    # A better place in another of the area's lists than `found_in`, or, for a title
    # Namesake's AI proposed, its best place in them: the evidence code orders venue and
    # map titles by (decision 20).
    listed_in: FoundIn | None = None


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
    # Where the venue is, from OpenStreetMap (Photon) by its name and address: Qloo gives
    # no coordinates (decision 4, revised). `point_tried` stops a second lookup.
    latitude: float | None = None
    longitude: float | None = None
    point_tried: bool = False
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


class ThinMap(BaseModel):
    title: Entity
    cells: int
    # Qloo could not tell which place was meant for this title's map (needs_input).
    unplaced: bool = False


class LocationProfile(BaseModel):
    location_id: str
    species: str | None = None
    # "seeds" for the fixed lookup, "agent" when the agent chose the titles and venues.
    made_by: str = "seeds"
    # Where the titles' order came from: Qloo's `rank`, or the agent when rank failed.
    order_source: str | None = None
    # Titles Namesake's AI proposed that Qloo neither ranked here nor listed in the area's
    # lists, left out because others had that evidence (decision 22).
    left_out_titles: list[str] = Field(default_factory=list)
    # False when no title had Qloo evidence for the area, so the AI's own were kept.
    titles_confirmed: bool = True
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
    # The first map title, left off the map for its thin map, when a spare did better.
    thin_map: ThinMap | None = None
    version: int = 1
    venues: list[Venue] = Field(default_factory=list)
    # How many venues the baseline's list held, when it was available to compare.
    baseline_venue_count: int | None = None
    # Whether the venues were asked within VENUE_GROUPS' categories: True, False when the area had
    # too few such places, None for a profile saved before (every place).
    venue_categories: bool | None = None
    cells: list[LiftCell] = Field(default_factory=list)
    # What the area watches in general: the second source for names.
    local_tastes: list[Entity] = Field(default_factory=list)
    calls: list[QlooCall] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Every call behind the venues and the map came back: the venues were compared and
        every map arrived (whether or not the maps overlap). An unfinished profile is saved
        with the AI's choices and finished on a later run (`finish_profile`)."""
        compared = bool(self.venues) and all(v.compared for v in self.venues)
        # Every map arrived: with cells, or answered empty (a place Qloo cannot map stays
        # without cells, and asking again would get the same cached answer).
        mapped = bool(self.cells) or bool(self.map_titles)
        return compared and mapped and self.maps_missing == 0


def baseline_titles(profile: LocationProfile) -> list[Entity]:
    """What the pet titles are compared with, for a profile of either version."""
    return profile.baselines or ([profile.baseline] if profile.baseline else [])


def layer_titles(profile: LocationProfile) -> list[Entity]:
    """The pet titles on the map, for a profile of either version."""
    return profile.map_titles or profile.pet_entities[:1]


def baseline_from_tastes(tastes: list[Entity], pets: list[Entity]) -> list[Entity]:
    """The area's top shows as the baseline, leaving out the pet titles themselves and any
    show whose name or description mentions animals: comparing a pet show with itself, or
    with another pet show, would hide the very thing the map is for. Shows whose name or
    description mentions a religion, race or politics are left out too: the page names the
    baseline as what people here tend to watch, and that must not read as a claim about who
    they are."""
    pet_ids = {e.id for e in pets}
    keep = [
        e
        for e in tastes
        if e.id not in pet_ids
        and not PET_WORDS.search(f"{e.name} {e.description or ''}")
        and not mentions_identity(e.name, e.description)
    ]
    return keep[:BASELINE_TITLES]


def coarsen(cells: dict[str, Any], size: int) -> dict[str, Any]:
    """A heatmap at a coarser geohash precision: finer cells under one coarser cell are
    averaged (score and centre)."""
    if all(len(g) == size for g in cells):
        return cells
    groups: dict[str, list[Any]] = {}
    for geohash, cell in cells.items():
        groups.setdefault(geohash[:size], []).append(cell)

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    return {
        g: SimpleNamespace(
            location=SimpleNamespace(
                latitude=mean([c.location.latitude for c in group]),
                longitude=mean([c.location.longitude for c in group]),
            ),
            query=SimpleNamespace(affinity=mean([c.query.affinity for c in group])),
        )
        for g, group in groups.items()
    }


def better_map(
    alt: dict[str, Any], thin: dict[str, Any], rest: list[dict[str, Any]], base: list[dict]
) -> bool:
    """Whether the spare title makes the better map in the first title's place: more cells
    with a comparison first (the map is about lift), then more cells."""

    def score(first: dict[str, Any]) -> tuple[int, int]:
        cells = combine_cells([m for m in [first, *rest] if m], [m for m in base if m])
        return sum(c.lift is not None for c in cells), len(cells)

    return score(alt) > score(thin)


def combine_cells(
    pet_maps: list[dict[str, Any]], base_maps: list[dict[str, Any]]
) -> list[LiftCell]:
    """One layer from several heatmaps. Each map's scores are ranks within the area (0 to
    1), so a cell's score is the mean over the maps that scored it; a cell no pet map
    scored is left out, and one no baseline map scored has no lift. Maps of different
    precision are brought to the coarsest one, so their cells line up."""
    cells: list[LiftCell] = []
    sizes = [len(g) for m in pet_maps + base_maps for g in m]
    size = min(sizes) if sizes else 0
    pet_maps = [coarsen(m, size) for m in pet_maps]
    base_maps = [coarsen(m, size) for m in base_maps]
    geohashes = list(dict.fromkeys(g for m in pet_maps for g in m))
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
        # Titles whose map Qloo could not place (needs_input).
        self.unplaced: set[str] = set()
        # Why the last call gave no answer: the exception it raised, or None.
        self.failure: Exception | None = None

    def call(self, operation: str, input_: dict[str, Any], purpose: str) -> Envelope | None:
        self.failure = None
        try:
            env = self.qloo.run(operation, input_)
        except ReplayMiss as exc:
            self.failure = exc
            self.profile.notes.append(f"Not precomputed yet: {purpose}.")
            return None
        except QlooExecError as exc:
            self.failure = exc
            self.profile.notes.append(f"Qloo could not be reached for {purpose}: {exc}")
            return None
        self.profile.calls.append(
            QlooCall(
                operation=operation, purpose=purpose, status=env.status, results=len(env.results)
            )
        )
        if env.status == "error":
            code = env.error.code if env.error else "unknown"
            self.failure = QlooExecError(f"Qloo returned an error ({code})")
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
                type=entity_type(c.type, seed.type),
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
            type=entity_type(r.get("type"), seed.type),
            description=props.get("short_description") or props.get("description"),
            why=seed.why,
        )

    def venues(
        self,
        signals: list[str],
        location: Location,
        purpose: str,
        *,
        complete: bool = False,
        filtered: bool = False,
    ) -> list[dict] | None:
        """Venue results, or None. With `complete`, a partial or degraded answer counts as none."""
        env = self.venue_answer(signals, location, purpose, filtered)
        return self.venue_results(env, purpose, complete=complete)

    def venue_answer(
        self, signals: list[str], location: Location, purpose: str, filtered: bool
    ) -> Envelope | None:
        """The venue question's answer as Qloo gave it, or None when it failed."""
        return self.call("recommend", venue_input(signals, location, filtered), purpose)

    def venue_results(
        self, env: Envelope | None, purpose: str, *, complete: bool = False, quiet: bool = False
    ) -> list[dict] | None:
        """The answer's places, or None; a note says why none, unless `quiet` (a probe whose
        answer may not be the one used)."""
        if env is None:
            return None
        if not env.has_results:
            if not quiet:
                self.profile.notes.append(f"Qloo returned no venues for {purpose}.")
            return None
        if complete and env.status != "ok":
            if not quiet:
                self.profile.notes.append(
                    f"Qloo's answer for {purpose} was {env.status}, so it is not used for "
                    "comparison."
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
        if env.status == "needs_input":
            # Qloo could not tell which place is meant. The answer is cached and final, so
            # the map counts as arrived, empty: finishing could never fetch it. The place,
            # not the title, is in question, so the note is said once.
            note = PLACE_NOTE.format(query=location.query)
            if note not in self.profile.notes:
                self.profile.notes.append(note)
            self.unplaced.add(entity.id)
            return {}
        if not env.has_results:
            # Answered with no cells: the map arrived, empty (a refusal is None).
            self.profile.notes.append(f"Qloo returned no map cells for {entity.name}.")
            return {}
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
            # A whole answer with no shows in it is usable: it says there are none.
            self.tastes_ok = env.status in ("ok", "empty")
            return []
        self.tastes_ok = env.status == "ok"
        return [
            Entity(
                id=r["entity_id"],
                name=r["name"],
                type=entity_type(r.get("type"), "tv_show"),
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


Prepared = tuple[list[Entity], list[Entity], str, list[str]]  # baseline_for's answer


def build_profile(
    qloo: QlooClient, location: Location, seeds: Seeds, prepared: Prepared | None = None
) -> LocationProfile:
    """The fixed lookup: seed titles, resolved by name, then the shared assembly.
    `prepared` is a baseline already looked up for this run, so it is not asked twice."""
    b = _Builder(qloo, location)
    pets = [e for e in (b.resolve(s) for s in seeds.pet) if e is not None]
    if not pets:
        return assemble_profile(b, location, pets, [])
    if prepared is None:
        tastes, baselines, source = area_baseline(b, location, seeds, pets)
        notes: list[str] = []
    else:
        # The prepared list was chosen before any pet title was known: choose again from
        # the same answer, so a seed title among the top shows is replaced, not dropped.
        tastes, baselines, source, notes = prepared
        if source == "area":
            baselines, source = choose_baseline(b, location, seeds, tastes, True, pets)
    profile = assemble_profile(b, location, pets, baselines)
    profile.local_tastes, profile.baseline_source = tastes, source
    profile.notes = notes + profile.notes
    return profile


def area_baseline(
    b: "_Builder", location: Location, seeds: Seeds, pets: list[Entity]
) -> tuple[list[Entity], list[Entity], str]:
    """The area's top shows and the baseline from them (decision 18): (tastes, baselines,
    source). When Qloo's list is unusable, or every top show mentions animals, the seed
    show stands in, and a note says so."""
    tastes = b.tastes(location)
    baselines, source = choose_baseline(b, location, seeds, tastes, b.tastes_ok, pets)
    return tastes, baselines, source


# Notes about the comparison itself start with this, so finishing a profile keeps them.
BASELINE_NOTE = "The comparison: "


def choose_baseline(
    b: "_Builder",
    location: Location,
    seeds: Seeds,
    tastes: list[Entity],
    usable: bool,
    pets: list[Entity],
) -> tuple[list[Entity], str]:
    """The baseline from an answer already in hand: the area's top shows when the answer
    is usable and leaves some, else the seed show, with a note either way it falls short."""
    baselines = baseline_from_tastes(tastes, pets) if usable else []
    if baselines:
        return baselines, "area"
    seed = b.resolve(seeds.baseline)
    if seed is None:
        b.profile.notes.append(
            f"{BASELINE_NOTE}none could be found, so the venues and the map are not compared."
        )
        return [], "seed"
    if not usable:
        why = (
            f"Qloo's list of the shows people around {location.label} watch most could not be used"
        )
    elif not tastes:
        why = f"Qloo returned no shows that people around {location.label} watch most"
    else:
        why = (
            f"every show people around {location.label} watch most mentions animals, is one "
            "of the pet titles here, or mentions a religion, race or politics"
        )
    b.profile.notes.append(
        f"{BASELINE_NOTE}{why}, so it is one widely watched show unrelated to pets: {seed.name}."
    )
    return [seed], "seed"


def baseline_for(
    qloo: QlooClient, location: Location, seeds: Seeds, pets: list[Entity] | None = None
) -> Prepared:
    """`area_baseline` on its own, with its notes: before the AI's run (no pet titles yet),
    or around titles already chosen (`finish_profile`)."""
    b = _Builder(qloo, location)
    tastes, baselines, source = area_baseline(b, location, seeds, pets or [])
    return tastes, baselines, source, b.profile.notes


def stale_baseline(profile: LocationProfile) -> bool:
    """A saved comparison that today's screen would not choose: a show whose name or
    description mentions a religion, race or politics (saved before that rule)."""
    return any(mentions_identity(e.name, e.description) for e in profile.baselines)


def needs_finishing(profile: LocationProfile) -> bool:
    """A saved profile to finish before use: an older version, missing parts, or a
    comparison chosen before today's screen. A visitor's run finishes current-version
    profiles only (`get_profile`); older versions are brought up by
    `app.upgrade_profiles`, which uses this whole test."""
    return profile.version < PROFILE_VERSION or not profile.complete or stale_baseline(profile)


def carry_points(src: LocationProfile, dst: LocationProfile) -> None:
    """Venue points placed on `src` (decision 4, revised), onto the same venues in `dst`
    where `dst` has none: a profile finished or placed meanwhile keeps both changes."""
    done = {v.entity_id: v for v in src.venues if v.point_tried}
    for venue in dst.venues:
        prior = done.get(venue.entity_id)
        if prior is not None and not venue.point_tried:
            venue.latitude, venue.longitude = prior.latitude, prior.longitude
            venue.point_tried = True


def finish_profile(
    old: LocationProfile, location: Location, qloo: QlooClient, seeds: Seeds
) -> LocationProfile | None:
    """The profile rebuilt at the current version around the titles already chosen,
    keeping what Namesake's AI chose (titles, order, venues and its reasons), with fixed
    calls only: cached ones are free, so only what was missing reaches Qloo. None when
    Qloo still could not complete it."""
    if not old.pet_entities:
        return None
    if old.baselines and not stale_baseline(old):
        # Finishing or upgrading from version 2: the baseline the AI's choices were made
        # against stays as it was; one that fails today's screen is chosen again below.
        tastes, baselines, source = old.local_tastes, old.baselines, old.baseline_source
        notes = [n for n in old.notes if n.startswith(BASELINE_NOTE)]
    else:
        tastes, baselines, source, notes = baseline_for(qloo, location, seeds, old.pet_entities)
    # The venues are asked as they were, so the AI's picks and reasons still match them;
    # a profile from before the categories keeps every place, and one whose venues never
    # arrived decides afresh.
    if old.venue_categories is None:
        filtered: bool | None = False
    else:
        filtered = old.venue_categories if old.venues else None
    new = profile_from(
        qloo, location, old.pet_entities, baselines, old.venue_signals or None, filtered
    )
    if not new.complete:
        return None
    reasons = {v.entity_id: (v.chosen_reason, v.rejected_reason) for v in old.venues}
    for venue in new.venues:
        venue.chosen_reason, venue.rejected_reason = reasons.get(venue.entity_id, (None, None))
    carry_points(old, new)  # placed before: no second lookup
    new.species, new.made_by = old.species, old.made_by
    new.left_out_titles, new.titles_confirmed = old.left_out_titles, old.titles_confirmed
    new.order_source, new.ranked = old.order_source, old.ranked
    if old.venue_categories is None:
        new.venue_categories = None  # from before decision 23: every place, as it was
    new.local_tastes, new.baseline_source = tastes, source
    new.notes = notes + new.notes
    # The lookups behind the titles stay on the record; the rest was asked again.
    new.calls = [c for c in old.calls if c.operation in ("describe", "rank")] + new.calls
    return new


def resolve_baseline(qloo: QlooClient, location: Location, seed: Seed) -> Entity | None:
    """The seed show on its own: the fallback probe for a typed area (decision 12). None
    when Qloo answered but no entry fits the seed's rule; a lookup that is not cached
    (live calls off), could not reach Qloo or came back as an error raises, so the check
    can be tried again."""
    b = _Builder(qloo, location)
    entity = b.resolve(seed)
    if entity is None and b.failure is not None:
        raise b.failure
    return entity


def assemble_profile(
    b: "_Builder",
    location: Location,
    pets: list[Entity],
    baselines: list[Entity],
    venue_signals: list[str] | None = None,
    filtered: bool | None = None,
) -> LocationProfile:
    """Venues for the pet titles and the baseline shows, compared, and the lift map.

    `venue_signals` are the titles the venues are asked for, when not all of
    `pets` (an agent asks for venues with its top few). Same input, same cache key.
    `filtered` is whether they are asked within VENUE_GROUPS' categories; None decides it here.
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
    base_venues = None
    if p.baselines:
        # Asked first: the comparison decides whether the area's venues are asked within
        # the categories, so both lists are asked the same way.
        filtered, base_venues = area_venues(b, location, p.baselines, filtered)
    purpose = f"venues near {location.label} for fans of pet-themed titles"
    if filtered is None:
        # No comparison decided it: the pet titles' own full answer does.
        env = b.venue_answer(p.venue_signals, location, purpose, True)
        filtered = not too_few(env)
        pet_venues = (
            b.venue_results(env, purpose)
            if filtered
            else b.venues(p.venue_signals, location, purpose)
        )
    else:
        pet_venues = b.venues(p.venue_signals, location, purpose, filtered=filtered)
    p.venue_categories = filtered
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
    ordered = list(
        {
            e.id: e for e in [by_id[i] for i in p.venue_signals if i in by_id] + p.pet_entities
        }.values()
    )
    p.map_titles = ordered[:MAP_TITLES]
    # The first pet title, then the baseline, then the rest, then a spare: if the key
    # refuses the last calls, the comparison survives and only an extra title is missing.
    first = [b.heatmap(e, location) for e in p.map_titles[:1]]
    base = [b.heatmap(e, location) for e in p.baselines]
    rest = [b.heatmap(e, location) for e in p.map_titles[1:]]
    base_maps = [m for m in base if m is not None]
    shown = {e.id for e in p.map_titles}
    spare = next((e for e in ordered if e.id not in shown), None)
    if first and first[0] is not None and len(first[0]) < THIN_MAP and spare is not None:
        # One extra call, only when the first map is thin: the next pet title may be
        # watched more here. Kept only if the map comes out better.
        notes, calls = len(p.notes), len(p.calls)
        alt = b.heatmap(spare, location)
        if alt and better_map(alt, first[0], [m for m in rest if m], base_maps):
            # The map's caption says it; the place note goes only when no map still in use
            # was unplaced (a baseline's may be).
            gone = {f"Qloo returned no map cells for {p.map_titles[0].name}."}
            in_use = {e.id for e in p.map_titles[1:] + p.baselines}
            if not in_use & b.unplaced:
                gone.add(PLACE_NOTE.format(query=location.query))
            p.notes = [n for n in p.notes if n not in gone]
            p.thin_map = ThinMap(
                title=p.map_titles[0],
                cells=len(first[0]),
                unplaced=p.map_titles[0].id in b.unplaced,
            )
            p.map_titles[0] = spare
            first = [alt]
        elif len(p.calls) > calls:
            # Qloo answered: say so in the call list. A map that was no better leaves no
            # notes, which say nothing about the map shown; an error keeps its note, the
            # only place its code is told. A failure to reach Qloo records no call, so
            # its note stays too.
            p.calls[-1].purpose += " (tried for a thin map, not used)"
            if p.calls[-1].status != "error":
                del p.notes[notes:]
    pet_maps = [m for m in first + rest if m is not None]
    p.maps_missing = len(p.map_titles) + len(p.baselines) - len(pet_maps) - len(base_maps)
    pet_maps, base_maps = [m for m in pet_maps if m], [m for m in base_maps if m]
    p.cells = combine_cells(pet_maps, base_maps)
    if p.cells and p.baselines and not any(c.lift is not None for c in p.cells):
        p.notes.append(
            "No map cell was scored for both the pet-themed titles and the shows they are compared "
            "with, so the map shows no comparison."
        )
    return p


def profile_from(
    qloo: QlooClient,
    location: Location,
    pets: list[Entity],
    baselines: list[Entity],
    venue_signals: list[str] | None = None,
    filtered: bool | None = None,
) -> LocationProfile:
    """Assemble a profile around titles chosen elsewhere (by the agent)."""
    return assemble_profile(
        _Builder(qloo, location), location, pets, baselines, venue_signals, filtered
    )


def area_venues(
    b: "_Builder", location: Location, baselines: list[Entity], filtered: bool | None = None
) -> tuple[bool | None, list[dict] | None]:
    """Whether the area's venues are asked within the categories, and the baseline shows'
    venues asked that way (None without a complete answer). Decided once per area, by the
    comparison's full answer: fewer than MIN_CATEGORY_VENUES such places (none included)
    and every place is used. A failed or incomplete answer decides nothing (None), and the
    pet titles' answer decides instead. `filtered` given keeps it as decided before."""
    purpose = f"venues near {location.label} for fans of the area's top shows"
    signals = [e.id for e in baselines]
    if filtered is not False:
        env = b.venue_answer(signals, location, purpose, True)
        # An incomplete baseline would make missing venues look distinctive. Noted only
        # when this answer is the one used, not when the fallback replaces it.
        results = b.venue_results(env, purpose, complete=True, quiet=True)
        if filtered or (results is not None and not too_few(env)):
            return True, b.venue_results(env, purpose, complete=True)
        if not too_few(env):
            b.venue_results(env, purpose, complete=True)  # its note: no comparison here
            return None, None
    return False, b.venues(signals, location, purpose, complete=True)


def baseline_venue_ids(
    qloo: QlooClient, location: Location, baselines: list[Entity]
) -> tuple[bool | None, list[str] | None]:
    """Whether the area's venues are asked within the categories, and the baseline shows'
    venues in rank order (None when there is no complete answer)."""
    filtered, results = area_venues(_Builder(qloo, location), location, baselines)
    return filtered, None if results is None else [r["entity_id"] for r in results]


def local_tastes(qloo: QlooClient, location: Location) -> list[Entity]:
    """What the area watches in general: the second source for names, and the baseline."""
    return _Builder(qloo, location).tastes(location)
