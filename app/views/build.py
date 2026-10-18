"""Build view models from domain objects. All user-facing wording lives here."""

import re
import time

from app.agent.checks import mentions_identity
from app.agent.results import ListingResult
from app.animals import Animal, LitterPhoto, Roster
from app.classify import bucket
from app.custom_location import MIN_CELLS
from app.listing import CHECK_SENTENCES, MIN_WORDS, cautions, templated_listing
from app.locations import Location
from app.places import MAX_PIN_KM
from app.profile import (
    Entity,
    LocationProfile,
    Venue,
    baseline_titles,
    layer_titles,
    rank_band,
)
from app.qloo.geohash import bounds
from app.views.models import (
    AddAnimalView,
    AnimalCard,
    ApprovedView,
    Credits,
    ExampleLink,
    ListingSentence,
    ListingVersion,
    ListingView,
    LitterCard,
    LitterMateView,
    LocationOption,
    MapCell,
    MapView,
    NameOptionView,
    NameView,
    Pin,
    PlanItem,
    Question,
    ResultView,
    ShelterBar,
    StartView,
    StepView,
    VenueView,
    WhyItem,
    WorkingView,
)

# The demo leads with the profile the research names as the US bottleneck.
FEATURED = "dog-02"
VENUES_SHOWN = 5
VENUES_IN_PLAN = 3
OBJECT_PRONOUN = {"female": "her", "male": "him"}
CHECK_LABELS = {
    "good_with_children": "children",
    "good_with_dogs": "dogs",
    "good_with_cats": "cats",
    "house_trained": "house-training",
    "bite_history": "bite history",
}


def result_id(animal_id: str, location_id: str) -> str:
    return f"{animal_id}@{location_id}"


def photo_url(image: str) -> str:
    return f"/static/animals/{image}"


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def sentences(text: str | None, limit: int = 220) -> str:
    """Whole sentences from the start of `text`, up to about `limit` characters.

    Qloo's descriptions can be long and are sometimes cut off mid-word.
    """
    if not text:
        return ""
    out = ""
    for part in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not part.endswith((".", "!", "?")) or (out and len(out) + len(part) > limit):
            break
        out = f"{out} {part}".strip()
    return out or text[:limit].rsplit(" ", 1)[0] + "…"


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def and_list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


PIN_FAR_NOTE = (
    f"The spot you picked is more than {MAX_PIN_KM} km from where Qloo has data for this "
    "area, so it is not shown. The circle marks the area Qloo checked."
)
PIN_NOTE = (
    "The pin is the spot you picked for the shelter. It stays in this visit and never "
    "goes to Qloo, which gets only the area's name."
)


def location_option(
    location: Location, selected: bool = False, pin: tuple[float, float] | None = None
) -> LocationOption:
    option = LocationOption(
        id=location.id,
        label=location.label,
        region=location.region,
        latitude=location.latitude,
        longitude=location.longitude,
        zoom=location.zoom,
        shelter_radius_m=shelter_radius(location),
        selected=selected,
    )
    if pin is not None:
        option.pin = Pin(latitude=pin[0], longitude=pin[1])
        option.map_note = PIN_NOTE
    return option


def shelter_radius(location: Location) -> float:
    """The circle around the fictional shelter, in metres: wider for a city."""
    return 800 * 2 ** (14 - location.zoom)


CLASSIFIER_CREDIT = (
    "Pet-themed titles sorted with TypeSafe's Jev classifier. Namesake is not affiliated with "
    "TypeSafe."
)
ADDED_PHOTO_CREDIT = (
    "The animal and its photo were added by you for this visit and are not stored. "
    "The shelter is fictional."
)
PLACEHOLDER_PHOTO = "/static/placeholder.svg"
# The precomputed examples, in the order the start page offers them.
EXAMPLES = (
    ("dog-02", "park-slope", "The lead dog in Park Slope"),
    ("dog-02", "astoria", "The same dog in Astoria"),
    ("kitten-01", "park-slope", "The litter, named as a set, in Park Slope"),
    ("kitten-01", "astoria", "The litter in Astoria"),
)


def added_photo_url(animal: Animal, has_photo: bool) -> str:
    return f"/photos/{animal.id}" if has_photo else PLACEHOLDER_PHOTO


def animal_card(animal: Animal, image_url: str | None = None) -> AnimalCard:
    added = image_url is not None
    return AnimalCard(
        id=animal.id,
        image_url=image_url or photo_url(animal.image),
        alt=animal.look,
        meta=" · ".join(x for x in [animal.group.capitalize(), animal.sex, animal.age] if x),
        look=animal.look[:1].upper() + animal.look[1:],
        temperament=animal.temperament[:1].upper() + animal.temperament[1:],
        litter=animal.litter is not None,
        featured=animal.id == FEATURED,
        badges=(["added by you"] if added else [])
        + (["litter"] if animal.litter else [])
        + (["long stay"] if any("months" in h for h in animal.history) else []),
    )


def litter_card(litter: LitterPhoto) -> LitterCard:
    return LitterCard(
        id=litter.id,
        image_url=photo_url(litter.image),
        alt=f"{len(litter.members)} kittens from the same litter",
        title="The whole litter",
        text=f"{len(litter.members)} kittens, named together as a set: every name comes from "
        "one title, and no two are the same.",
    )


def example_links(ready: set[tuple[str, str]], ui_query: str = "") -> list[ExampleLink]:
    return [
        ExampleLink(label=label, url=f"/result?animal={a}&location={loc}{ui_query}")
        for a, loc, label in EXAMPLES
        if (a, loc) in ready
    ]


def build_start_view(
    roster: Roster,
    locations: list[Location],
    selected_id: str,
    *,
    examples: list[ExampleLink] | None = None,
    added: list[AnimalCard] | None = None,
    pins: dict[str, tuple[float, float]] | None = None,
    pin_far: bool = False,
) -> StartView:
    animals = sorted(roster.animals, key=lambda a: a.id != FEATURED)
    options = [
        location_option(loc, loc.id == selected_id, (pins or {}).get(loc.id)) for loc in locations
    ]
    for option in options:
        if pin_far and option.selected:
            option.map_note = PIN_FAR_NOTE
    chosen = next((o for o in options if o.selected), None)
    shelter = (
        # A spot dropped as too far is explained in the panel, so it opens.
        ShelterBar(name=chosen.label, region=chosen.region, open=pin_far)
        if chosen
        else ShelterBar(name="not chosen yet", chosen=False, open=True)
    )
    return StartView(
        shelter=shelter,
        map_note=(chosen or options[0]).map_note,
        examples=examples or [],
        title="Write an adoption listing",
        intro=(
            "Pick the shelter's area and an animal. Namesake drafts a plain listing from the "
            "facts the shelter recorded, and a plan for getting the animal seen, using Qloo "
            "taste data about pet-themed shows near the shelter."
        ),
        locations=options,
        animals=(added or []) + [animal_card(a) for a in animals],
        litters=[litter_card(lit) for lit in roster.litters],
    )


def basis_label(key: str) -> str:
    if key == "temperament":
        return "Temperament, as staff describe it"
    if key == "look":
        return "Recorded look"
    return "Recorded fact" if key.startswith("fact:") else "Confirmed by the shelter"


def copy_block(name: str | None, hook: str | None, text: str) -> str:
    return "\n\n".join(x for x in [f"Meet {name}." if name else None, hook, text] if x)


def listing_view(
    animal: Animal,
    result: ListingResult | None,
    profile: LocationProfile,
    generic: str | None,
    refined: str | None = None,
) -> ListingView:
    draft = result.draft if result else None
    if draft is not None:
        bio = [(s.text, s.facts) for s in result.bio]
        written_by = (
            "Written by Namesake's AI from the shelter's records; code adds the confirmed "
            "answers and checks every sentence."
        )
    else:
        bio = [(s.text, [s.source]) for s in templated_listing(animal).sentences]
        written_by = "Built from the shelter's records by a fixed template."
    text = " ".join(t for t, _ in bio)
    word_count = len(text.split())
    sentences = [
        ListingSentence(text=t, basis=", ".join(dict.fromkeys(basis_label(k) for k in keys)))
        for t, keys in bio
    ]
    unknown = [
        CHECK_LABELS[field]
        for field in CHECK_SENTENCES
        if getattr(animal.checks, field) == "unknown"
    ]
    left_out = []
    if unknown:
        left_out.append(f"Not yet known, so not mentioned: {and_list(unknown)}.")
    if animal.history:
        left_out.append("Backstory and time in the shelter are kept for staff, not printed.")

    local_name = draft.names[0].name if draft else None
    local_hook = result.hook if draft else None
    versions = [
        ListingVersion(
            variant="generic",
            label="Generic",
            available=generic is not None,
            name=generic,
            name_source="A common pet name from a fixed list, not from Qloo.",
            copy_text=copy_block(generic, None, text) if generic else "",
            note=None
            if generic
            else "Every name on the generic list is already used at this shelter.",
            selected=draft is None and generic is not None,
        ),
        ListingVersion(
            variant="local",
            label="Local, with Qloo",
            available=draft is not None,
            name=local_name,
            name_source=(
                name_badge(
                    draft.names[0].source,
                    draft.names[0].entity_id,
                    profile,
                    title_names(profile, result).get(draft.names[0].entity_id),
                )
                if draft
                else ""
            ),
            hook=local_hook,
            copy_text=copy_block(local_name, local_hook, text) if draft else "",
            note=None
            if draft
            else "No local version yet: it needs the name options from Namesake's AI.",
            selected=draft is not None,
        ),
    ]
    return ListingView(
        heading="The listing",
        text=text,
        sentences=sentences,
        word_count=word_count,
        short_note=(
            "Short because the shelter has recorded only a few facts. Add observations "
            "(behaviour with people, other animals, on the lead) for a full listing of "
            f"{MIN_WORDS} words or more."
            if word_count < MIN_WORDS
            else None
        ),
        left_out=left_out,
        versions=versions,
        toggle_note=(
            "Both versions share the same bio. The local one adds a name drawn from Qloo "
            "taste data near the shelter and one line saying where the name comes from."
        ),
        fallback_note=result.fallback_reason if result else None,
        refined_note=(
            f"Refined at your request (“{refined}”). Only you see this version."
            if refined
            else None
        ),
        written_by=written_by,
        must_keep=cautions(animal),
    )


def title_names(profile: LocationProfile, result: ListingResult | None) -> dict[str, str]:
    """Every title a name may come from, by Qloo ID: the area's, then this animal's lookalikes."""
    names = {e.id: e.name for e in profile.pet_entities + profile.local_tastes}
    for look in result.lookalikes if result else []:
        names.setdefault(look.entity.id, look.entity.name)
    return names


def name_badge(
    source: str, entity_id: str, profile: LocationProfile, title: str | None = None
) -> str:
    """Claim local strength only where Qloo's ranking for this area says so."""
    if source == "lookalike":
        return f"Has a lookalike in {title}" if title else "Has a lookalike"
    if source == "local":
        return "Watched locally"
    found = next((e.found_in for e in profile.pet_entities if e.id == entity_id), None)
    liked = f"liked here by fans of {found.signal}" if found else None
    if entity_id in profile.ranked:
        place = profile.ranked.index(entity_id) + 1
        ranked = f"ranked {ordinal(place)} of {len(profile.ranked)} here by Qloo"
        return f"Pet-themed title, {ranked}" + (f"; {liked}" if liked else "")
    return f"Pet-themed title, {liked}" if liked else "Pet-themed title"


def name_view(result: ListingResult | None, profile: LocationProfile, text: str) -> NameView:
    draft = result.draft if result else None
    if draft is None:
        return NameView(
            value=None,
            placeholder="No name yet: the name options from Namesake's AI appear after a run.",
        )
    titles = title_names(profile, result)
    refs = result.references
    options = []
    for i, o in enumerate(draft.names):
        reference = refs[i] if i < len(refs) else o.character
        options.append(
            NameOptionView(
                name=o.name,
                badge=name_badge(o.source, o.entity_id, profile, titles.get(o.entity_id)),
                title=titles.get(o.entity_id, o.character),
                reference=reference,
                why=o.why,
                hook=f"Named after {reference}.",
                copy_text=copy_block(o.name, f"Named after {reference}.", text),
            )
        )
    return NameView(value=draft.names[0].name, placeholder="", options=options)


def compared_with(profile: LocationProfile) -> str | None:
    """Whom the pet titles' fans are compared with, as words: the area's top shows (profile
    version 2), the single seed show (version 1), or None without a baseline."""
    if profile.baselines and profile.baseline_source == "area":
        return "fans of this area's top shows"
    shows_ = baseline_titles(profile)
    return f"fans of {and_list([e.name for e in shows_])}" if shows_ else None


def shows(n: int) -> str:
    return f" ({n} shows)" if n > 1 else ""


def map_view(
    location: Location, profile: LocationProfile, pin: tuple[float, float] | None = None
) -> MapView:
    titles = layer_titles(profile)
    pets = f"fans of {and_list([e.name for e in titles])}" if titles else "pet-show fans"
    base = compared_with(profile) or "a baseline"
    cells = []
    for c in profile.cells:
        south, west, north, east = bounds(c.geohash)
        if c.lift is None:
            label = f"Scored for {pets}{shows(c.pet_count)} only; no comparison here."
        else:
            label = (
                f"{cap(pets)}: {c.pet_score:.2f}{shows(c.pet_count)}; "
                f"{base}: {c.baseline_score:.2f}{shows(c.baseline_count)}."
            )
        cells.append(
            MapCell(
                geohash=c.geohash,
                south=south,
                west=west,
                north=north,
                east=east,
                lift=c.lift,
                label=label,
            )
        )
    thin = ""
    if 0 < len(cells) < MIN_CELLS:
        # A typed area passes its check on the area's own top show; its pet titles may
        # still map thinly (decision 12), and the page says so.
        thin = (
            f"Only {len(cells)} map cell{'s' if len(cells) != 1 else ''} here: Qloo's data for "
            f"pet-show fans around {location.label} is thin, so the map says little. "
        )
    return MapView(
        latitude=location.latitude,
        longitude=location.longitude,
        zoom=location.zoom,
        shelter_radius_m=shelter_radius(location),
        pin=Pin(latitude=pin[0], longitude=pin[1]) if pin else None,
        cells=cells,
        legend=thin
        + (
            (
                f"Warm cells: {pets} rank this part of {location.label} higher than {base} do. "
                "Cool cells: lower. Grey: only the pet shows have a score there. Where several "
                "shows scored a cell, their scores are averaged. Scores are ranks within the "
                "area, so they compare places here, not with other cities."
            )
            if any(c.lift is not None for c in cells)
            else f"Cells: where {pets} rank high within {location.label}. No cell was also "
            f"scored for {base}, so the map shows no comparison here."
        ),
        note=(
            f"Warm: pet-show fans stand out here more than {base}. Cool: less. Grey: no comparison."
            if any(c.lift is not None for c in cells)
            else "Grey: no cell was scored for both, so there is no comparison here."
            if cells
            else None
        ),
        empty_message=None if cells else "No map data for this area yet.",
    )


RANK_NOTES = {
    "top": "near the top of Qloo's list",
    "middle": "middle of Qloo's list",
    "bottom": "near the bottom of Qloo's list",
}


def venue_order(profile: LocationProfile) -> list[Venue]:
    """The venues to suggest, never screened ones.

    When the agent built the profile, only the places it chose: its judgement is a
    positive selection, not just the absence of a rejection. The fixed lookup has no
    judgement, so it suggests places that stand out, then the rest.
    """
    suitable = [v for v in profile.venues if v.unsuitable is None]
    if profile.made_by == "agent":
        return sorted((v for v in suitable if v.chosen_reason), key=lambda v: v.rank)
    return sorted(suitable, key=lambda v: (not v.distinctive, v.rank))


def venue_view(v: Venue, location: Location, profile: LocationProfile) -> VenueView:
    # Name only the titles the venues were asked for.
    asked = set(profile.venue_signals) or {e.id for e in profile.pet_entities}
    pets = and_list([e.name for e in profile.pet_entities if e.id in asked])
    base = compared_with(profile)
    total = len(profile.venues)
    evidence = (
        f"Ranked {ordinal(v.rank)} of {total} places near {location.label} for fans of {pets}"
    )
    if not v.compared or base is None:
        evidence += "; not compared with a baseline."
        badge = "Not compared"
    elif v.distinctive:
        evidence += f"; not among the {profile.baseline_venue_count} places for {base}."
        badge = "Stands out for pet-show fans"
    else:
        evidence += f"; also {ordinal(v.baseline_rank)} for {base}."
        badge = "Popular nearby generally"
    band = rank_band(v.rank, total)
    return VenueView(
        name=v.name,
        place=", ".join(x for x in [v.neighbourhood, v.address] if x),
        description=sentences(v.description) or None,
        stands_out=v.distinctive,
        badge=badge,
        rank=f"{ordinal(v.rank)} of {total}",
        rank_band=band,
        rank_note=RANK_NOTES[band],
        evidence=evidence,
        chosen=v.chosen_reason is not None,
        reason=v.chosen_reason,
    )


def plan(animal: Animal, location: Location, venues: list[Venue]) -> list[PlanItem]:
    items = [
        PlanItem(
            text="Share the listing through the personal networks of foster carers and volunteers.",
            basis="Research",
        ),
        PlanItem(
            text=(
                f"Take the {animal.species} on an outing or to an event in an “Adopt Me” vest."
                if animal.species == "dog"
                else f"Bring the {animal.species} to a meet-and-greet session at an event."
            ),
            basis="Research",
        ),
        PlanItem(text="Post on Friday or Saturday, or in the early evening.", basis="Research"),
    ]
    if animal.species == "dog" and location.city == "New York City":
        items.append(
            PlanItem(
                text="Send the listing to rescue partners and foster recruiters: in New York they "
                "take more of the city shelter's dogs than walk-in adopters do.",
                basis="Research",
            )
        )
    top = [v.name for v in venues[:VENUES_IN_PLAN]]
    if top:
        items.append(
            PlanItem(
                text=f"Ask {and_list(top)} about hosting an adoption event or a flyer.",
                basis="Qloo",
            )
        )
    if location.community_channel:
        items.append(
            PlanItem(text=f"Also reach {location.community_channel}.", basis="Our suggestion")
        )
    return items


KIND_WORDS = {"tv_show": "TV shows", "movie": "films", "book": "books"}


def sorted_by(e: Entity) -> str:
    """The classifier's answers for a title, as our reading: they are not Qloo's."""
    v = e.verdict
    sure = "kept it as clearly pet-themed" if bucket(v) == "kept" else "left it to Namesake's AI"
    return (
        f"A classifier (TypeSafe's Jev) read Qloo's description and {sure}: about pets "
        f"{v.pets:.2f}, dogs {v.dogs:.2f}, cats {v.cats:.2f}, family audience {v.family:.2f}, "
        f"real people {v.real_people:.2f} (each a probability from 0 to 1)."
    )


def listed(e: Entity, location: Location) -> str:
    """Where a title Namesake's AI proposed also sits in one of the area's lists."""
    f = e.listed_in
    if f is None:
        return ""
    return (
        f"Also {ordinal(f.position)} of {f.out_of} in Qloo's list of "
        f"{KIND_WORDS.get(f.kind, 'titles')} people around {location.label} who like "
        f"{f.signal} tend to like. "
    )


def why(location: Location, profile: LocationProfile) -> tuple[list[WhyItem], list[WhyItem]]:
    returned, reading = [], []
    # A saved comparison show today's screen would not choose is never named (decision 18);
    # the next run chooses the comparison again.
    hidden = {e.id for e in baseline_titles(profile) if mentions_identity(e.name, e.description)}
    for e in profile.pet_entities + [b for b in baseline_titles(profile) if b.id not in hidden]:
        kind = e.type.removeprefix("urn:entity:").replace("_", " ")
        if e.resolution == "chosen":
            returned.append(
                WhyItem(
                    title=f"{e.name} ({kind})",
                    detail=f"Qloo has {e.alternatives + 1} entries with this name. "
                    + listed(e, location)
                    + sentences(e.description),
                )
            )
        elif e.found_in:
            f = e.found_in
            what = KIND_WORDS.get(f.kind, "titles")
            returned.append(
                WhyItem(
                    title=f"{e.name} ({kind})",
                    detail=f"{ordinal(f.position)} of {f.out_of} in Qloo's list of {what} "
                    f"people around {location.label} who like {f.signal} tend to like. "
                    + listed(e, location)
                    + sentences(e.description),
                )
            )
        else:
            returned.append(
                WhyItem(
                    title=f"{e.name} ({kind})",
                    detail=listed(e, location) + sentences(e.description),
                )
            )
    for e in profile.pet_entities:
        detail = f"A pet-themed pick: {e.why.rstrip('.')}."
        if e.choice_reason:
            detail += f" {cap(e.choice_reason.rstrip('.'))}."
        reading.append(WhyItem(title=f"Why {e.name}", detail=detail))
        if e.verdict:
            reading.append(WhyItem(title=f"How {e.name} was sorted", detail=sorted_by(e)))
    if profile.made_by == "agent":
        reading.append(
            WhyItem(
                title="Who chose",
                detail="Namesake's AI proposed the titles, settled ambiguous names and picked "
                "the venues; code chose which titles the venues were asked for, by Qloo's "
                "evidence, and checked that each came from Qloo. "
                + (
                    "It also searched Qloo's lists for what people here who like its titles "
                    "tend to like, and kept the pet-themed ones. "
                    if any(e.found_in for e in profile.pet_entities)
                    else ""
                )
                + (
                    "The order of the titles is Qloo's ranking for this area."
                    if profile.order_source == "qloo_rank"
                    else "Qloo's ranking was unavailable, so the order is the one Namesake's AI "
                    "chose."
                ),
            )
        )
    if profile.baselines and profile.baseline_source == "area":
        named = [e.name for e in profile.baselines if e.id not in hidden]
        lead = f"{and_list(named)}: the TV shows" if named else "The TV shows"
        later = ""
        if hidden and not named:
            later = (
                " They were chosen before that rule and are not named here; the next run "
                "chooses them again."
            )
        elif hidden:
            later = (
                " One of them was chosen before that rule and is not named here; the next run "
                "chooses it again."
            )
        reading.append(
            WhyItem(
                title="Why compare with this area's top shows",
                detail=f"{lead} Qloo ranks highest for people around {location.label}, leaving "
                "out any whose name or description mentions animals, a religion, race or "
                "politics. A place or map cell that ranks high for their fans too is popular "
                f"here generally, not because of pets.{later}",
            )
        )
    elif baseline_titles(profile):
        seed = baseline_titles(profile)[0]
        reading.append(
            WhyItem(
                title=f"Why compare with {seed.name}",
                detail=f"{cap(seed.why or 'a widely watched show unrelated to pets')}. Places "
                "and map cells that rank high for both are popular generally, not because of "
                "pets.",
            )
        )
    if profile.venues:
        pets = and_list([e.name for e in profile.pet_entities])
        shared = sum(1 for v in profile.venues if v.compared and not v.distinctive)
        returned.append(
            WhyItem(
                title=f"{len(profile.venues)} places near {location.label}",
                detail=f"Ranked for people who like {pets}"
                + (
                    f"; {shared} of them also rank for {compared_with(profile)}."
                    if compared_with(profile) and profile.venues[0].compared
                    else "."
                ),
            )
        )
    excluded = [f"{v.name} ({v.unsuitable})" for v in profile.venues if v.unsuitable]
    if excluded:
        reading.append(WhyItem(title="Left out as event venues", detail=and_list(excluded) + "."))
    if profile.cells:
        returned.append(
            WhyItem(
                title=f"{len(profile.cells)} map cells within {location.label}",
                detail="Scored by Qloo from 0 to 1, as ranks within the area.",
            )
        )
    if any(c.lift is not None for c in profile.cells):
        reading.append(
            WhyItem(
                title="Lift on the map",
                detail="The pet shows' score minus the score for "
                f"{compared_with(profile) or 'the baseline'} in the same cell, each averaged over "
                "the shows that scored it. It is relative: "
                "where in this area pet-show fans stand out, not how many there are.",
            )
        )
    for call in profile.calls:
        returned.append(
            WhyItem(
                title=f"qloo {call.operation}",
                detail=f"{cap(call.purpose)}: {call.status}, {call.results} results.",
            )
        )
    return returned, reading


def lookalike_why(
    animal: Animal, result: ListingResult | None
) -> tuple[list[WhyItem], list[WhyItem]]:
    """What Qloo returned for each lookalike title, and the agent's reading of the match."""
    returned, reading = [], []
    if result is None or result.draft is None:
        return returned, reading
    reasons = {o.entity_id: o.choice_reason for o in result.draft.names}
    for look in result.lookalikes:
        e = look.entity
        kind = e.type.removeprefix("urn:entity:").replace("_", " ")
        found = "Found in Qloo. "
        if look.chosen:
            several = f"{look.candidates} candidates" if look.candidates > 1 else "one candidate"
            found = f"Qloo asked which title was meant and offered {several}. "
        returned.append(
            WhyItem(title=f"{e.name} ({kind})", detail=found + sentences(e.description))
        )
        qloo_part = (
            "Namesake's AI chose this title among Qloo's candidates"
            if look.chosen
            else "Qloo confirmed the title"
        )
        detail = (
            f"{look.animal} in it shares this {animal.species}'s recorded look: "
            f"{and_list(look.shared_look)}. That match is the reading of Namesake's AI; "
            f"{qloo_part}, not how its animals look."
        )
        if look.chosen and reasons.get(e.id):
            detail += f" Why this one: {reasons[e.id].rstrip('.')}."
        reading.append(WhyItem(title=f"Why {e.name}", detail=detail))
    return returned, reading


def build_result_view(
    animal: Animal,
    location: Location,
    profile: LocationProfile,
    listing: ListingResult | None = None,
    *,
    generic: str | None = "Biscuit",
    refined: str | None = None,
    litter: list[LitterMateView] | None = None,
    image_url: str | None = None,
    pin: tuple[float, float] | None = None,
) -> ResultView:
    ordered = venue_order(profile)
    returned, reading = why(location, profile)
    look_returned, look_reading = lookalike_why(animal, listing)
    returned, reading = look_returned + returned, look_reading + reading
    named = [m for m in litter or [] if m.name]
    listing_ = listing_view(animal, listing, profile, generic, refined)
    return ResultView(
        id=result_id(animal.id, location.id),
        animal=animal_card(animal, image_url),
        location=location_option(location, True),
        litter=litter or [],
        litter_note=("Named as a set with the rest of the litter:" if len(named) > 1 else None),
        name=name_view(listing, profile, listing_.text),
        listing=listing_,
        chosen_name=listing.draft.names[0].name if listing and listing.draft else None,
        map=map_view(location, profile, pin),
        venues=[venue_view(v, location, profile) for v in ordered[:VENUES_SHOWN]],
        plan_heading=f"Get {OBJECT_PRONOUN.get(animal.sex or '', 'them')} seen",
        plan=plan(animal, location, ordered),
        qloo_returned=returned,
        our_reading=reading,
        notes=profile.notes,
        credits=Credits(
            **({"photos": ADDED_PHOTO_CREDIT} if image_url else {}),
            classifier=CLASSIFIER_CREDIT if any(e.verdict for e in profile.pet_entities) else None,
        ),
    )


def build_working_view(
    run, animal: Animal, location: Location, ui_query: str = "", image_url: str | None = None
) -> WorkingView:
    return WorkingView(
        run_id=run.id,
        title=f"Working on the listing for this {animal.species} in {location.label}",
        animal=animal_card(animal, image_url),
        credits=Credits(photos=ADDED_PHOTO_CREDIT) if image_url else Credits(),
        location=location_option(location, True),
        events_url=f"/api/runs/{run.id}/events",
        result_url=run.result_url + ui_query,
        steps=[StepView(kind=s.kind, text=s.text) for s in run.log.steps],
        finished=run.log.finished,
        seconds_since_step=int(time.time() - run.log.steps[-1].at) if run.log.steps else 0,
    )


def build_approved_view(
    approval_id: str,
    result: ResultView,
    variant_label: str,
    copy_text: str,
    name: str,
    name_source: str,
    edited: bool,
    back_url: str,
) -> ApprovedView:
    return ApprovedView(
        id=approval_id,
        title=f"{name} is ready to post",
        animal=result.animal,
        location=result.location,
        variant_label=variant_label,
        copy_text=copy_text,
        recorded=[
            f"Approval {approval_id}, with the time.",
            f"The animal and the shelter area ({result.location.label}).",
            f"The version: {variant_label.lower()}.",
            f"The name, {name}, and where it came from: {name_source}.",
            "Whether you edited the text" + (" (you did)." if edited else " (you did not)."),
            "Not the text itself. This is what a trial of generic against local listings "
            "would compare against adoption dates and returns.",
        ],
        back_url=back_url,
        credits=result.credits,
    )


def build_add_animal_view(
    location_id: str, max_facts: int, error: str | None = None
) -> AddAnimalView:
    return AddAnimalView(
        location_id=location_id,
        questions=[
            Question(field=field, label=label)
            for field, label in [
                ("good_with_children", "Good with children?"),
                ("good_with_dogs", "Good with dogs?"),
                ("good_with_cats", "Good with cats?"),
                ("house_trained", "House-trained?"),
                ("bite_history", "A bite on record?"),
            ]
        ],
        max_facts=max_facts,
        error=error,
    )
