"""Build view models from domain objects. All user-facing wording lives here."""

import re
import time

from app.agent.checks import mentions_identity
from app.agent.listing_agent import Lookalike, NameOption
from app.agent.results import ListingResult
from app.animals import Animal, LitterPhoto, Roster
from app.classify import bucket
from app.custom_location import MIN_CELLS
from app.listing import CHECK_SENTENCES, MIN_WORDS, cautions, pronouns, templated_listing
from app.locations import Location
from app.places import MAX_PIN_KM, distance_km
from app.profile import (
    LEFT_OUT_GROUPS,
    MIN_CATEGORY_VENUES,
    VENUE_GROUPS,
    Entity,
    FoundIn,
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
    QlooPart,
    Question,
    ResultView,
    ShelterBar,
    StartView,
    StepView,
    VenuePin,
    VenueView,
    WhyItem,
    WorkingView,
)

# The demo leads with the profile the research names as the US bottleneck.
FEATURED = "dog-02"
VENUES_SHOWN = 5
VENUES_IN_PLAN = 3
# Within this, a place gets a walking estimate and the map frames its pin.
WALKABLE_KM = 3
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


LOCAL_LABEL = "Local, with Qloo"


def local_choice(name: str | None) -> str:
    """The local version's toggle button: its label and, once there is one, its name."""
    return f"{LOCAL_LABEL} · {name}" if name else LOCAL_LABEL


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
        left_out.append("Backstory and time in the shelter stay out of the listing.")

    local_name = draft.names[0].name if draft else None
    local_hook = result.hook if draft else None
    versions = [
        ListingVersion(
            variant="generic",
            label="Generic",
            choice=f"Generic · {generic}" if generic else "Generic",
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
            label=LOCAL_LABEL,
            choice=local_choice(local_name),
            available=draft is not None,
            name=local_name,
            name_source=(
                name_badge(
                    draft.names[0].source,
                    draft.names[0].entity_id,
                    profile,
                    lookalike_of(result, draft.names[0].entity_id),
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
    source: str, entity_id: str, profile: LocationProfile, look: Lookalike | None = None
) -> str:
    """What Qloo returned for a name's title. Claim local strength only where Qloo's
    evidence for this area says so: its ranking here, or the title's place in one of the
    area's lists. A lookalike's match is the AI's reading (see `look_line`), so Qloo's part
    is only the title: found, or offered among candidates when Qloo asked which was meant."""
    if source == "lookalike":
        return "Offered as a candidate" if look and look.chosen else "Title found"
    if source == "local":
        return "Watched locally"
    entity = next((e for e in profile.pet_entities if e.id == entity_id), None)
    found = (entity.found_in or entity.listed_in) if entity else None
    liked = None
    if found:
        liked = (
            "in Qloo's list for this area asked with its pet tags"
            if found.by_tags
            else f"liked here by fans of {found.signal}"
        )
    if entity_id in profile.ranked:
        place = profile.ranked.index(entity_id) + 1
        ranked = f"ranked {ordinal(place)} of {len(profile.ranked)} here by Qloo"
        return f"Pet-themed title, {ranked}" + (f"; {liked}" if liked else "")
    return f"Pet-themed title, {liked}" if liked else "Pet-themed title"


def lookalike_of(result: ListingResult | None, entity_id: str) -> Lookalike | None:
    return (
        next((k for k in result.lookalikes if k.entity.id == entity_id), None) if result else None
    )


def look_line(option: NameOption, look: Lookalike | None) -> str:
    """For a lookalike's name, the AI's match in front of its reason: Qloo found the title,
    not the look."""
    if option.source != "lookalike":
        return ""
    if look is None or not look.shared_look:
        return "A lookalike. "
    shared = and_list(look.shared_look)
    # The reference before it names the character, so this part does not.
    return f"A lookalike, matched on this animal's recorded look ({shared}). "


def approved_source(option: NameOption, badge: str, title: str, look: Lookalike | None) -> str:
    """Where an approved name came from, as the approval records it."""
    if option.source == "lookalike":
        qloo = "Qloo found the title"
        if look and look.chosen:
            qloo = (
                "Qloo offered the title among candidates"
                if look.candidates > 1
                else "Qloo offered the title as its one candidate"
            )
        return f"a lookalike title, {title}: {qloo}, and the match is the reading of Namesake's AI"
    return f"Qloo, {badge[:1].lower()}{badge[1:]}: {title}"


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
        look = lookalike_of(result, o.entity_id)
        badge = name_badge(o.source, o.entity_id, profile, look)
        title = titles.get(o.entity_id, o.character)
        options.append(
            NameOptionView(
                name=o.name,
                badge=badge,
                title=title,
                # Under the name, a lookalike's fragment needs its title beside it.
                header_source=f"{badge}: {title}" if o.source == "lookalike" else badge,
                approved_source=approved_source(o, badge, title, look),
                reference=reference,
                why=look_line(o, look) + o.why,
                hook=f"Named after {reference}.",
                copy_text=copy_block(o.name, f"Named after {reference}.", text),
                version_choice=local_choice(o.name),
            )
        )
    return NameView(value=draft.names[0].name, placeholder="", options=options)


def groups_in() -> str:
    return and_list([f"{name} ({why})" for name, _, why in VENUE_GROUPS])


def groups_out() -> str:
    return and_list([f"{name} ({why})" for name, why in LEFT_OUT_GROUPS])


def venues_note(profile: LocationProfile, species: str) -> str | None:
    """Under "Places to ask": which kinds of place Qloo was asked for and why, which were not
    asked for, and that the places belong to the area, not to this animal."""
    if not profile.venues:
        return None
    shared = (
        f"The same places for every {species} at this shelter; the name and the listing are "
        "this animal's."
    )
    if profile.venue_categories:
        return (
            f"Qloo was asked only for places that can host an adoption stand or take a flyer: "
            f"{groups_in()}. Not asked for: {groups_out()}; Qloo's tags are broad, so a few "
            f"others can appear. {shared}"
        )
    if profile.venue_categories is False:
        return (
            f"Qloo's list of places of the usual kinds (cafes and breweries, bookshops and pet "
            f"shops, community places) here held fewer than {MIN_CATEGORY_VENUES}, so it was "
            f"asked for places of any kind. {shared}"
        )
    return shared


def kinds_reading(profile: LocationProfile) -> str:
    if profile.venue_categories:
        return (
            f"Namesake asked Qloo for these kinds only: {groups_in()}. Not asked for: "
            f"{groups_out()}. "
            "Without them Qloo's list near a spot is mostly what is popular there, such as an "
            "arena, whatever the titles. Qloo tags places broadly, so a few others come "
            "through; the code screen and Namesake's AI judge each."
        )
    return (
        f"Qloo's list of places of the usual kinds (cafes and breweries, bookshops and pet "
        f"shops, community places) for this area held fewer than {MIN_CATEGORY_VENUES}, so it "
        "was asked for places of any kind."
    )


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
    location: Location,
    profile: LocationProfile,
    pin: tuple[float, float] | None = None,
    venues: list[Venue] | None = None,
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
    swap = ""
    if profile.thin_map and titles:
        t = profile.thin_map
        by_id = {e.id: e for e in profile.pet_entities}
        asked = [by_id[i] for i in profile.venue_signals if i in by_id] or profile.pet_entities
        what = (
            f"Qloo could not place {t.title.name}'s map within {location.label}"
            if t.unplaced
            else f"Qloo returned {t.cells} map cell{'s' if t.cells != 1 else ''} for "
            f"{t.title.name} within {location.label}"
        )
        swap = (
            f"{what}, so the map uses {titles[0].name} in its "
            f"place. The places to ask are for fans of {and_list([e.name for e in asked])}. "
        )
    key = (
        f"Warm: pet-show fans stand out here more than {base}. Cool: less, or level. "
        "Grey: no comparison."
        if any(c.lift is not None for c in cells)
        else "Grey: no cell was scored for both, so there is no comparison here."
        if cells
        else None
    )
    swapped = (
        f" Mapped: {titles[0].name}, in place of {profile.thin_map.title.name}."
        if profile.thin_map and titles
        else ""
    )
    thin = ""
    if 0 < len(cells) < MIN_CELLS:
        # A typed area passes its check on the area's own top show; its pet titles may
        # still map thinly (decision 12), and the page says so.
        thin = (
            f"Only {len(cells)} map cell{'s' if len(cells) != 1 else ''} here: Qloo's data for "
            f"pet-show fans around {location.label} is thin, so the map says little. "
        )
    placed = [
        v
        for v in venues or []
        if v.latitude is not None
        and in_view(v, profile, pin or (location.latitude, location.longitude))
    ]
    compared = [c.lift for c in cells if c.lift is not None]
    # Counted as the map colours them (above zero is warm; a tie is cool), so a reader
    # counting warm cells gets this number.
    warm = sum(lift > 0 for lift in compared)
    which = "" if len(compared) == len(cells) else " with a comparison"
    some = "these" if len(compared) == len(cells) else "the"
    if not compared or thin:
        # A thin map already says it says little; a count would read as more.
        count = ""
    elif len(compared) == 1:
        verb = "stand out" if warm else "do not stand out"
        count = f"{cap(pets)} {verb} against {base} in the one cell{which}. "
    elif not warm:
        count = f"{cap(pets)} do not stand out against {base} in any of {some} cells{which}. "
    elif warm == len(compared):
        count = f"{cap(pets)} stand out against {base} in all {warm} cells{which}. "
    else:
        count = (
            f"{cap(pets)} stand out against {base} in {warm} of {some} "
            f"{len(compared)} cells{which}. "
        )
    numbers = (
        " Numbers: the places to ask plotted here, as numbered in the list (points from "
        "OpenStreetMap)."
        if placed
        else ""
    )
    return MapView(
        latitude=location.latitude,
        longitude=location.longitude,
        zoom=location.zoom,
        shelter_radius_m=shelter_radius(location),
        pin=Pin(latitude=pin[0], longitude=pin[1]) if pin else None,
        cells=cells,
        venues=[
            VenuePin(
                number=n,
                name=v.name,
                latitude=v.latitude,
                longitude=v.longitude,
                in_view=in_view(v, profile, pin or (location.latitude, location.longitude)),
            )
            for n, v in enumerate(venues or [], start=1)
            if v.latitude is not None
            and v.longitude is not None
            # A pin the map does not frame would be off screen: the card says so instead.
            and in_view(v, profile, pin or (location.latitude, location.longitude))
        ],
        legend=swap
        + thin
        + count
        + (
            (
                f"Warm cells: {pets} rank this part of {location.label} higher than {base} do. "
                "Cool cells: lower, or level. Grey: only the pet shows have a score there. "
                "Where several "
                "shows scored a cell, their scores are averaged. Scores are ranks within the "
                "area, so they compare places here, not with other cities."
            )
            if any(c.lift is not None for c in cells)
            else f"Cells: where {pets} rank high within {location.label}. No cell was also "
            f"scored for {base}, so the map shows no comparison here."
        ),
        note=((key + swapped + numbers) if key else None),
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


def venue_titles(profile: LocationProfile) -> str:
    """The titles the venues were asked for, in that order: every pet title for a profile
    saved before `venue_signals` was kept. The plan keeps those titles since decision 20's
    revision; an older profile that dropped them gets a plain description instead."""
    if not profile.venue_signals:
        return and_list([e.name for e in profile.pet_entities])
    by_id = {e.id: e for e in profile.pet_entities}
    asked = [by_id[i].name for i in profile.venue_signals if i in by_id]
    # An older profile may have searched with titles it no longer keeps; never name
    # others in their place.
    return and_list(asked) if asked else "the pet-themed titles searched"


def cell_of(v: Venue, profile: LocationProfile):
    """The lift cell a placed venue falls in, or None."""
    if v.latitude is None or v.longitude is None:
        return None
    for c in profile.cells:
        south, west, north, east = bounds(c.geohash)
        if south <= v.latitude <= north and west <= v.longitude <= east:
            return c
    return None


def cell_reading(
    v: Venue,
    location: Location,
    profile: LocationProfile,
    shelter: tuple[float, float] | None = None,
) -> str | None:
    """Where OpenStreetMap places a venue on the lift map, read in the map's own terms:
    ranks within the area, for pet-show fans as a group against the comparison shows."""
    if v.latitude is None or v.longitude is None:
        return None
    c = cell_of(v, profile)
    if c is None and not in_view(v, profile, shelter or (location.latitude, location.longitude)):
        return "OpenStreetMap places it beyond the map's view."
    if c is None:
        return "OpenStreetMap places it outside the mapped cells."
    if c.lift is None:
        return "OpenStreetMap places it in a cell with no comparison."
    base = compared_with(profile) or "the comparison shows"
    how = "higher than" if c.lift > 0 else "lower than" if c.lift < 0 else "as high as"
    return (
        f"OpenStreetMap places it where pet-show fans rank this part of {location.label} "
        f"{how} {base} do ({c.lift:+.2f})."
    )


def walk(v: Venue, shelter: tuple[float, float]) -> str | None:
    """Straight-line distance from the shelter; a walking estimate (5 km/h) when near."""
    if v.latitude is None or v.longitude is None:
        return None
    km = distance_km(shelter, (v.latitude, v.longitude))
    text = f"{km:.1f} km from the shelter in a straight line"
    if km <= WALKABLE_KM:
        text += f", about {max(1, round(km / 5 * 60))} min on foot"
    return text + "."


def in_view(v: Venue, profile: LocationProfile, shelter: tuple[float, float]) -> bool:
    """Whether the map should frame this pin: in a cell, or close to the shelter."""
    return cell_of(v, profile) is not None or (
        distance_km(shelter, (v.latitude, v.longitude)) <= WALKABLE_KM
    )


def venue_view(
    v: Venue,
    location: Location,
    profile: LocationProfile,
    number: int = 0,
    shelter: tuple[float, float] | None = None,
) -> VenueView:
    pets = venue_titles(profile)
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
        number=number,
        where=cell_reading(v, location, profile, shelter),
        distance=walk(v, shelter or (location.latitude, location.longitude)),
    )


def plan(
    animal: Animal, location: Location, venues: list[Venue], skipped: list[Venue] | None = None
) -> list[PlanItem]:
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
    if skipped:
        skip = and_list([f"{v.name} (it mentions {mentions(v)})" for v in skipped])
        items.append(
            PlanItem(
                text=f"Skip {skip} for this {animal.species}: the record says "
                f"{pronouns(animal.sex)['they']} {pronouns(animal.sex)['is']} not good with "
                "children.",
                basis="Our suggestion",
            )
        )
    if location.community_channel:
        items.append(
            PlanItem(text=f"Also reach {location.community_channel}.", basis="Our suggestion")
        )
    return items


# Venues whose name or own Qloo description mentions children: skipped, per animal, when
# the record says the animal is not good with children (decision 2). Whole words, so
# "kid-friendly", "child care" and "Childrens Museum" count; words with other common
# meanings in venue text ("nursery" for plants, "daycare" for dogs, "baby back ribs",
# "youth hostel", a dog park's "play area") are not on the list. A venue with no
# description is judged by its name.
FOR_CHILDREN = re.compile(
    r"\b(child|children|childrens|kid|kids|toddlers?|babies|playgrounds?|playgroups?"
    r"|preschools?|kindergartens?|elementary[- ]schools?|childcare|family[- ]friendly"
    r"|families|storytime|soft[- ]play)\b"
)


def for_children(name: str | None, description: str | None = None) -> str | None:
    """The word in a venue's name or description that is about children, or None."""
    match = FOR_CHILDREN.search(f"{name or ''} {description or ''}".lower())
    return match.group(1) if match else None


def venues_for_animal(animal: Animal, venues: list[Venue]) -> tuple[list[Venue], list[Venue]]:
    """The venues to suggest, in order, and those skipped: for an animal recorded as not
    good with children, a venue whose name or Qloo description mentions children. Unknown
    and yes keep them all; the record alone decides, never a guess about the area."""
    if animal.checks.good_with_children != "no":
        return venues, []
    skipped = [v for v in venues if for_children(v.name, v.description)]
    skip = {v.entity_id for v in skipped}
    return [v for v in venues if v.entity_id not in skip], skipped


def skipped_shown(every: list[Venue], kept: list[Venue], skipped: list[Venue]) -> list[Venue]:
    """The skipped venues the page would have shown: those among the first VENUES_SHOWN,
    and any ranked above the last venue it does show (a lower one took their slot)."""
    shown = kept[:VENUES_SHOWN]
    cut = max(every.index(shown[-1]) + 1 if shown else 0, VENUES_SHOWN)
    skip = {v.entity_id for v in skipped}
    return [v for v in every[:cut] if v.entity_id in skip]


def mentions(v: Venue) -> str:
    """The child word a skipped venue mentions, quoted (only skipped venues are named)."""
    word = for_children(v.name, v.description)
    return f"“{word or 'children'}”"


KIND_WORDS = {"tv_show": "TV shows", "movie": "films", "book": "books"}
KIND_SINGULAR = {"tv_show": "TV show", "movie": "film", "book": "book"}


def kind_word(e: Entity, default: str | None = "tv_show") -> str:
    """A title's kind for the page: "TV show", "film", "book". Profiles saved before
    `entity_type` may hold Qloo's generic type: then the kind comes from where the title
    was found, else `default` (the area's top shows and comparison shows are all TV; a
    lookalike may be anything, so it reads as a "title")."""
    if e.type.startswith("urn:entity:"):
        kind = e.type.removeprefix("urn:entity:")
    elif ":" not in e.type:
        kind = e.type  # a bare kind
    else:
        kind = e.found_in.kind if e.found_in else default
    if not kind:
        return "title"
    return KIND_SINGULAR.get(kind, kind.replace("_", " "))


def sorted_by(e: Entity) -> str:
    """The classifier's answers for a title, as our reading: they are not Qloo's."""
    v = e.verdict
    sure = "kept it as clearly pet-themed" if bucket(v) == "kept" else "left it to Namesake's AI"
    return (
        f"A classifier (TypeSafe's Jev) read Qloo's description and {sure}: about pets "
        f"{v.pets:.2f}, dogs {v.dogs:.2f}, cats {v.cats:.2f}, family audience {v.family:.2f}, "
        f"real people {v.real_people:.2f} (each a probability from 0 to 1)."
    )


def place_in_list(f: FoundIn, location: Location) -> str:
    """Where a title sits in one of the area's lists, as Qloo returned it."""
    what = KIND_WORDS.get(f.kind, "titles")
    if f.by_tags:
        return (
            f"{ordinal(f.position)} of {f.out_of} in Qloo's list of {what} people around "
            f"{location.label} tend to like, asked with Qloo's pet tags."
        )
    return (
        f"{ordinal(f.position)} of {f.out_of} in Qloo's list of {what} people around "
        f"{location.label} who like {f.signal} tend to like."
    )


def listed(e: Entity, location: Location, also: bool = True) -> str:
    """A better place in another of the area's lists, or where a title Namesake's AI
    proposed also sits in one of them."""
    if not e.listed_in:
        return ""
    return ("Also " if also else "") + place_in_list(e.listed_in, location) + " "


def who_chose(profile: LocationProfile) -> str:
    """Who decided the area's titles, venues and order: Qloo's part apart from the AI's."""
    by_tags = any(e.found_in and e.found_in.by_tags for e in profile.pet_entities)
    searched = any(
        f and not f.by_tags for e in profile.pet_entities for f in (e.found_in, e.listed_in)
    )
    sorted_ = any(e.verdict for e in profile.pet_entities)
    if by_tags:
        text = (
            "Qloo listed titles people here tend to like, asked with its pet tags"
            + (", and a classifier sorted them" if sorted_ else "")
            + "; Namesake's AI judged the unclear ones, could add its own, settled ambiguous "
            "names and picked the venues. "
        )
    else:
        text = "Namesake's AI proposed the titles, settled ambiguous names and picked the venues. "
    if searched:
        text += (
            "It also searched Qloo's lists for what people here who like its titles tend to "
            "like, and kept the pet-themed ones. "
        )
    if profile.left_out_titles:
        text += (
            f"Code left out {and_list(profile.left_out_titles)}: Qloo neither ranks "
            f"{'them' if len(profile.left_out_titles) > 1 else 'it'} here nor lists "
            f"{'them' if len(profile.left_out_titles) > 1 else 'it'} for this area. "
        )
    elif not profile.titles_confirmed and profile.made_by == "agent":
        text += (
            "None of the titles kept has Qloo's ranking or a place in the area's lists, so "
            "they are Namesake's AI's own. "
        )
    text += (
        "Code chose which titles the venues were asked for, by Qloo's evidence, and checked "
        "that each came from Qloo. "
    )
    return text + (
        "The order of the titles is Qloo's ranking for this area."
        if profile.order_source == "qloo_rank"
        else "Qloo's ranking was unavailable, so the order is the one Namesake's AI chose."
    )


def why(location: Location, profile: LocationProfile) -> tuple[list[WhyItem], list[WhyItem]]:
    returned, reading = [], []
    # A saved comparison show today's screen would not choose is never named (decision 18);
    # the next run chooses the comparison again.
    hidden = {e.id for e in baseline_titles(profile) if mentions_identity(e.name, e.description)}
    for e in profile.pet_entities + [b for b in baseline_titles(profile) if b.id not in hidden]:
        kind = kind_word(e)
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
            returned.append(
                WhyItem(
                    title=f"{e.name} ({kind})",
                    detail=place_in_list(e.found_in, location)
                    + " "
                    + listed(e, location)
                    + sentences(e.description),
                )
            )
        else:
            returned.append(
                WhyItem(
                    title=f"{e.name} ({kind})",
                    detail=listed(e, location, also=False) + sentences(e.description),
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
                detail=who_chose(profile),
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
        pets = venue_titles(profile)
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
    if profile.venues and profile.venue_categories is not None:
        reading.append(WhyItem(title="Kinds of place asked for", detail=kinds_reading(profile)))
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
        kind = kind_word(e, default=None)
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
        match = (
            f"{look.animal} in it shares this {animal.species}'s recorded look: "
            f"{and_list(look.shared_look)}."
            if look.shared_look
            else f"{look.animal} in it is offered as a lookalike for this {animal.species}."
        )
        detail = (
            f"{match} That match is the reading of Namesake's AI; "
            f"{qloo_part}, not how its animals look."
        )
        if look.chosen and reasons.get(e.id):
            detail += f" Why this one: {reasons[e.id].rstrip('.')}."
        reading.append(WhyItem(title=f"Why {e.name}", detail=detail))
    return returned, reading


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def qloo_part(
    location: Location, profile: LocationProfile, listing: ListingResult | None
) -> QlooPart:
    """Qloo's part of this result and the AI's, counted from what the profile holds: no
    calls, nothing invented. Each part says only what that party did: Qloo returned the
    lists, rankings, places and maps; the AI judged, picked and wrote."""
    pets = profile.pet_entities
    ranked = [e for e in pets if e.id in profile.ranked]
    listed = [e for e in pets if e.found_in or e.listed_in]
    backed = [e for e in pets if e in ranked or e in listed]
    qloo = []
    if backed:
        # Each title counted once: ranked, else only in Qloo's lists for the area.
        only_listed = [e for e in listed if e not in ranked]
        how = and_list(
            ([f"{len(ranked)} ranked here"] if ranked else [])
            + ([f"{len(only_listed)} only in its lists for the area"] if only_listed else [])
        )
        qloo.append(
            f"{plural(len(backed), 'title')} with Qloo's evidence for {location.label} ({how})"
        )
    elif pets:
        qloo.append(f"{plural(len(pets), 'title')} looked up")
    if profile.venues:
        qloo.append(
            f"{plural(len(profile.venues), 'place')} near the shelter, ranked for fans of "
            f"{venue_titles(profile)}"
        )
    if profile.cells:
        qloo.append(f"{plural(len(profile.cells), 'map cell')} from its heatmaps")
    qloo_text = cap("; ".join(qloo)) + "." if qloo else f"Nothing for {location.label} yet."

    ai = []
    agent = profile.made_by == "agent"
    if agent:
        own = [e for e in pets if not e.found_in]
        judged = [e for e in pets if e.found_in and bucket(e.verdict) != "kept"]
        picked = [v for v in profile.venues if v.chosen_reason]
        if own:
            ai.append(f"proposed {plural(len(own), 'title')} for Qloo to check")
        if judged:
            ai.append(f"judged {plural(len(judged), 'unclear title')}")
        if picked:
            ai.append(f"picked {len(picked)} of the places to ask")
        if len(pets) > 1 and profile.order_source != "qloo_rank":
            ai.append("set the order, as Qloo's ranking was unavailable")
    draft = listing.draft if listing else None
    if draft is not None:
        ai.append("chose the names and wrote the bio from the shelter's records")
    if ai:
        ai_text = cap("; ".join(ai)) + "."
        if draft is None:
            ai_text += " The names and bio are the fixed template."
        if not agent:
            ai_text += " The titles are a fixed lookup."
    elif agent:
        ai_text = "Kept the titles above; the names and bio are the fixed template."
    else:
        ai_text = (
            "Not used here: the titles are a fixed lookup, and the names and bio a fixed template."
        )
    return QlooPart(qloo=qloo_text, ai=ai_text)


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
    every = venue_order(profile)
    ordered, skipped = venues_for_animal(animal, every)
    named_skips = skipped_shown(every, ordered, skipped)
    shown = ordered[:VENUES_SHOWN]
    # Whether a venue the page would not have shown now takes a slot.
    first = {v.entity_id for v in every[:VENUES_SHOWN]}
    moved_up = any(v.entity_id not in first for v in ordered[:VENUES_SHOWN])
    returned, reading = why(location, profile)
    if named_skips:
        # Our reading of Qloo's venues for this animal; Qloo's column stays as it was.
        reading.append(
            WhyItem(
                title=f"Skipped for this {animal.species}",
                detail=and_list(
                    [
                        f"{v.name}: its name or Qloo description mentions {mentions(v)}"
                        for v in named_skips
                    ]
                )
                + f". The record says this {animal.species} is not good with children"
                + (", and the next places take their slots." if moved_up else "."),
            )
        )
    if any(v.latitude is not None for v in shown):
        reading.append(
            WhyItem(
                title="The places on the map",
                detail="Qloo gives each place an address but no point on the map, so Namesake "
                "looked the suggested places up once in OpenStreetMap (Photon), by name and "
                "address. Where a pin falls among the cells, and its distance from the "
                "shelter, are Namesake's reading.",
            )
        )
    looks_returned, looks_read = lookalike_why(animal, listing)
    returned, reading = looks_returned + returned, looks_read + reading
    named = [m for m in litter or [] if m.name]
    listing_ = listing_view(animal, listing, profile, generic, refined)
    return ResultView(
        id=result_id(animal.id, location.id),
        animal=animal_card(animal, image_url),
        location=location_option(location, True),
        litter=litter or [],
        litter_note=("Named as a set with the rest of the litter:" if len(named) > 1 else None),
        qloo_part=qloo_part(location, profile, listing),
        name=name_view(listing, profile, listing_.text),
        listing=listing_,
        chosen_name=listing.draft.names[0].name if listing and listing.draft else None,
        map=map_view(location, profile, pin, shown),
        venues=[venue_view(v, location, profile, n, pin) for n, v in enumerate(shown, start=1)],
        venues_note=venues_note(profile, animal.species),
        venues_empty=(
            f"Every place Namesake would suggest here mentions children, so none is suggested "
            f"for this {animal.species}."
            if every and not ordered
            else "No venues for this area yet."
        ),
        plan_heading=f"Get {OBJECT_PRONOUN.get(animal.sex or '', 'them')} seen",
        plan=plan(animal, location, ordered, named_skips),
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
