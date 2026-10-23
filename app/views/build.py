"""Build view models from domain objects. All user-facing wording lives here."""

import re
import time
from urllib.parse import urlencode

from app.agent.checks import hook_text, mentions_identity
from app.agent.listing_agent import Lookalike, NameOption, shown_bio
from app.agent.results import ListingResult
from app.animals import Animal, LitterPhoto, Roster
from app.audience import NOTE as AUDIENCE_NOTE
from app.audience import audience_line
from app.classify import bucket
from app.config import get_settings
from app.custom_location import MIN_CELLS
from app.listing import (
    CHECK_SENTENCES,
    MAX_WORDS,
    MIN_WORDS,
    cautions,
    pronouns,
    recorded_past,
    templated_listing,
)
from app.locations import Location
from app.places import distance_km
from app.profile import (
    LEFT_OUT_GROUPS,
    MIN_CATEGORY_VENUES,
    VENUE_GROUPS,
    Entity,
    FoundIn,
    LocationProfile,
    Venue,
    baseline_titles,
    chain_name,
    layer_titles,
    rank_band,
    screen,
)
from app.qloo.geohash import bounds
from app.views.models import (
    TYPED_AREA,
    ActorKey,
    AddAnimalView,
    AnimalCard,
    ApprovedView,
    AreaCheckView,
    Credits,
    ExampleLink,
    FlyerPlace,
    FlyerView,
    Link,
    ListingSentence,
    ListingVersion,
    ListingView,
    LitterCard,
    LitterMateView,
    LocationOption,
    MapCell,
    MapTiles,
    MapView,
    NameOptionView,
    NameView,
    Pin,
    PlanItem,
    ProcessStep,
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
# Places farther than this from the shelter's point are left out (decision 40): a
# volunteer does not cross a city for a flyer. Only a place with a pin can be measured.
MAX_VENUE_KM = 5
OBJECT_PRONOUN = {"female": "her", "male": "him"}
POSSESSIVE = {"female": "her", "male": "his"}
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


# A sentence ends at . ! or ?, but not after an initial or a title: "Michael J. Fox" and
# "Dr. Oakley" stay whole (22 October walkthrough).
SENTENCE_END = re.compile(
    r"(?<=[.!?])(?<!\b[A-Z]\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bSt\.)(?<!\bJr\.)"
    r"(?<!\bSr\.)(?<!\bMrs\.)\s+"
)


def sentences(text: str | None, limit: int = 220) -> str:
    """Whole sentences from the start of `text`, up to about `limit` characters.

    Qloo's descriptions can be long and are sometimes cut off mid-word.
    """
    if not text:
        return ""
    out = ""
    for part in SENTENCE_END.split(text.strip()):
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


PIN_NOTE = (
    "The pin is the spot you picked for the shelter. It stays in this visit and never "
    "goes to Qloo, which gets only the area's name."
)


OSM_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)
CARTO_ATTRIBUTION = OSM_ATTRIBUTION + ' &copy; <a href="https://carto.com/attributions">CARTO</a>'
# CARTO's raster basemaps take the key as `?key=` (carto.com/basemaps, "Get your API key").
CARTO_TILES = "https://{{s}}.basemaps.cartocdn.com/{style}/{{z}}/{{x}}/{{y}}{{r}}.png?key={key}"
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def map_tiles(key: str | None = None) -> MapTiles:
    """The basemap for every map: CARTO's Positron (light) and Dark Matter (dark) with the
    `MAP_TILES_KEY` setting, else OpenStreetMap's standard tiles. The key goes to the
    browser on purpose: tile requests come from there (AGENTS.md, Secrets)."""
    if key is None:
        secret = get_settings().map_tiles_key
        key = secret.get_secret_value() if secret else ""
    if key:
        return MapTiles(
            url=CARTO_TILES.format(style="light_all", key=key),
            dark_url=CARTO_TILES.format(style="dark_all", key=key),
            attribution=CARTO_ATTRIBUTION,
            subdomains="abcd",
            max_zoom=20,
            # A keyed basemap that keeps failing gives way to OpenStreetMap's tiles.
            fallback_url=OSM_TILES,
            fallback_attribution=OSM_ATTRIBUTION,
        )
    return MapTiles(
        url=OSM_TILES, dark_url=OSM_TILES, attribution=OSM_ATTRIBUTION, subdomains="", max_zoom=19
    )


# What a typed area's region said before 19 October (decision 29); areas stored then keep it.
OLD_TYPED_REGION = "Typed location"


def place_of(location: Location) -> str:
    """The area as one phrase: "Park Slope, Brooklyn, New York", or a typed area's name."""
    if location.region and location.region != OLD_TYPED_REGION:
        return f"{location.label}, {location.region}"
    return location.label


def location_option(
    location: Location, selected: bool = False, pin: tuple[float, float] | None = None
) -> LocationOption:
    option = LocationOption(
        id=location.id,
        label=location.label,
        region="" if location.region == OLD_TYPED_REGION else location.region,
        place=place_of(location),
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
    """The circle around the sample shelter, in metres: wider for a city."""
    return 800 * 2 ** (14 - location.zoom)


REPO_URL = "https://github.com/bsabau/namesake"
RESEARCH_URL = f"{REPO_URL}/blob/main/docs/research/adoption-evidence-review.md"
TRIAL_URL = f"{REPO_URL}#measuring-whether-it-works"
# The problem in one line for the start page, worded within the evidence review's claims.
PROBLEM = (
    "Volunteers write a listing for every animal, often with little time. Namesake keeps "
    "to what the research supports: a plain listing that states only the recorded facts, "
    "names screened before they are offered, and a plan for getting the animal seen. "
    "Local taste data is the labelled experiment."
)
# Whether the local version helps is untested; the page says so, and what would test it.
TRIAL = (
    "Does the local version help? Nobody has tested it yet. Namesake records each "
    "approved version so a shelter network could: generic against local, assigned at "
    "random, measured in days to adoption, with about 190 adoptions to detect a 50% "
    "faster rate, more if several shelters take part."
)
CLASSIFIER_CREDIT = (
    "Pet-themed titles sorted with TypeSafe's Jev classifier. Namesake is not affiliated with "
    "TypeSafe."
)
ADDED_PHOTO_CREDIT = (
    "The animal and its photo were added by you and are kept in your workspace only. "
    "The shelter is a sample."
)
WORKSPACE_NOTE = (
    "No sign-up: your workspace lives in this browser for 7 days after your last visit. "
    "Copy its link to open it on another device; anyone with the link can open it."
)
PLACEHOLDER_PHOTO = "/static/placeholder.svg"
# The precomputed examples, in the order the start page offers them.
EXAMPLES = (
    # Each label says who and where; the second of a pair says "the same", so it reads as
    # one animal in two areas, not a second one.
    ("dog-02", "park-slope", "The brindle dog in Park Slope"),
    ("dog-02", "astoria", "The same brindle dog in Astoria"),
    ("cat-01", "park-slope", "The shy black cat in Park Slope"),
    ("cat-01", "astoria", "The same black cat in Astoria"),
    # A bite on record and not for a home with children: the listing says both (decision 41).
    ("dog-03", "park-slope", "The border collie-type mix with a bite on record, in Park Slope"),
)


def added_photo_url(animal: Animal, has_photo: bool) -> str:
    return f"/photos/{animal.id}" if has_photo else PLACEHOLDER_PHOTO


CONFIRMED_LINES = {
    "good_with_children": {"yes": "Good with children", "no": "Not for a home with children"},
    "good_with_dogs": {"yes": "Gets on with dogs", "no": "Best without other dogs"},
    "good_with_cats": {"yes": "Gets on with cats", "no": "Best without cats"},
    "house_trained": {"yes": "House-trained", "no": "Not yet house-trained"},
    "bite_history": {"yes": "A bite on record", "no": "No bite on record"},
}


def recorded_facts(animal: Animal) -> list[str]:
    """The shelter's record as short lines: the observed facts, then the confirmed answers,
    each as the record has it. Nothing unrecorded, and nothing read into it."""
    confirmed = [
        CONFIRMED_LINES[field][answer]
        for field in CHECK_SENTENCES
        if (answer := getattr(animal.checks, field)) in CONFIRMED_LINES.get(field, {})
    ]
    return [cap(f.rstrip(".")) for f in animal.facts] + confirmed


def unknown_checks(animal: Animal) -> list[str]:
    return [
        CHECK_LABELS[field]
        for field in CHECK_SENTENCES
        if getattr(animal.checks, field) == "unknown"
    ]


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
        own=added,
        badges=(["added by you"] if added else [])
        + (["litter"] if animal.litter else [])
        + (["long stay"] if any("months" in h for h in animal.history) else []),
        facts=recorded_facts(animal),
        unknown=unknown_checks(animal),
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
    workspace_link: str = "",
) -> StartView:
    """`workspace_link` opens the visitor's workspace in another browser; shown with their
    own animals only."""
    animals = sorted(roster.animals, key=lambda a: a.id != FEATURED)
    samples = [animal_card(a) for a in animals]
    options = [
        location_option(loc, loc.id == selected_id, (pins or {}).get(loc.id)) for loc in locations
    ]
    chosen = next((o for o in options if o.selected), None)
    shelter = (
        ShelterBar(name=chosen.label, region=chosen.region)
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
        problem=PROBLEM,
        problem_link=Link(label="What the research says", url=RESEARCH_URL),
        locations=options,
        map_tiles=map_tiles(),
        animals=(added or []) + samples,
        your_animals=added or [],
        sample_animals=samples,
        workspace_note=WORKSPACE_NOTE if added else "",
        workspace_link=workspace_link if added else "",
        add_animal_label="Add another animal" if added else "Add your own animal",
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
# The same version when its name's title has no Qloo evidence for the area: Qloo found
# the title, but nothing in its data for the area singles it out.
FOUND_LABEL = "With Qloo"


def area_backed(profile: LocationProfile) -> set[str]:
    """Titles with Qloo's evidence for the area: ranked here, in Qloo's lists for it, or
    among what people there tend to watch. A title only looked up is not among them."""
    backed = {e.id for e in profile.pet_entities if e.id in profile.ranked}
    backed |= {e.id for e in profile.pet_entities if e.found_in or e.listed_in}
    return backed | {e.id for e in profile.local_tastes}


def is_local(option: NameOption, profile: LocationProfile) -> bool:
    """A name counts as local only when its title has Qloo's evidence for the area; a
    lookalike's title is matched to the animal, not the area."""
    return option.source != "lookalike" and option.entity_id in area_backed(profile)


def local_label(local: bool) -> str:
    return LOCAL_LABEL if local else FOUND_LABEL


def local_choice(name: str | None, local: bool) -> str:
    """The local version's toggle button: its label and, once there is one, its name."""
    return f"{local_label(local)} · {name}" if name else local_label(local)


def listing_view(
    animal: Animal,
    result: ListingResult | None,
    profile: LocationProfile,
    generic: str | None,
    refined: str | None = None,
) -> ListingView:
    draft = result.draft if result else None
    if draft is not None:
        # Today's confirmed answers, never those saved with the draft, so a record
        # changed since (a bite added, decision 41) shows on every page, the visitor's
        # refined listings included.
        bio = [(s.text, s.facts) for s in shown_bio(animal, draft)]
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
    unknown = unknown_checks(animal)
    left_out = []
    if unknown:
        left_out.append(f"Not yet known, so not mentioned: {and_list(unknown)}.")
    past = recorded_past(animal)
    if past:
        quoted = and_list([f"“{fact}”" for fact in past])
        left_out.append(
            f"The record mentions a past or pleads for the animal ({quoted}); the listing "
            "repeats it as recorded. A listing works best describing the animal as it is "
            "now, so reword or remove it before approving, unless it carries a warning."
        )
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
            label=local_label(draft is None or is_local(draft.names[0], profile)),
            choice=local_choice(local_name, draft is None or is_local(draft.names[0], profile)),
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
            # A saved draft passed the bound with the answers as they were; today's may be
            # longer (decision 41), and they are never cut.
            else f"Over {MAX_WORDS} words because the shelter's confirmed answers changed "
            "after this listing was written. Keep them, and trim another sentence when you "
            "edit it."
            if draft is not None and word_count > MAX_WORDS
            else None
        ),
        left_out=left_out,
        versions=versions,
        toggle_note=(
            "Both versions share the same bio. The one with Qloo adds a name from a title "
            "Qloo returned and one line saying where the name comes from; it is called local "
            "only when Qloo's data for the area backs that title."
        ),
        fallback_note=result.fallback_reason if result else None,
        refined_note=(
            f"Refined at your request (“{refined}”)"
            + (
                ""
                if not (result and result.draft) or result.names_kept is None
                else ": the bio is rewritten and the names are kept"
                if result.names_kept
                else ": the names are changed too"
            )
            + ". Only you see this version."
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
        # Its place in Qloo's list of what people around the area tend to watch, the one
        # the area's names come from when no pet title gives one.
        ids = [e.id for e in profile.local_tastes]
        if entity_id in ids:
            place = ids.index(entity_id) + 1
            return (
                f"Watched locally: {ordinal(place)} of {len(ids)} in Qloo's list of what "
                "people here tend to watch"
            )
        return "Not among the titles Qloo listed as what people here tend to watch"
    entity = next((e for e in profile.pet_entities if e.id == entity_id), None)
    found = (entity.found_in or entity.listed_in) if entity else None
    liked = None
    if found:
        liked = (
            "in Qloo's list for this area, asked with its pet tags"
            if found.by_tags
            else f"liked here by fans of {found.signal}"
        )
    if entity_id in profile.ranked:
        place = profile.ranked.index(entity_id) + 1
        ranked = f"ranked {ordinal(place)} of {len(profile.ranked)} here by Qloo"
        return f"Pet-themed title, {ranked}" + (f"; {liked}" if liked else "")
    if liked:
        return f"Pet-themed title, {liked}"
    # A pet title can also be one of the area's top tastes: that is Qloo's evidence too.
    watched = [e.id for e in profile.local_tastes]
    if entity_id in watched:
        place = watched.index(entity_id) + 1
        return (
            f"Pet-themed title, {ordinal(place)} of {len(watched)} in Qloo's list of what "
            "people here tend to watch"
        )
    return "Pet-themed title, not among the titles in Qloo's pet-themed lists for this area"


def lookalike_of(result: ListingResult | None, entity_id: str) -> Lookalike | None:
    return (
        next((k for k in result.lookalikes if k.entity.id == entity_id), None) if result else None
    )


def look_line(option: NameOption, look: Lookalike | None) -> str:
    """In front of the AI's reason: for a lookalike's name, the AI's match (Qloo found the
    title, not the look); for any other name, that the character is the AI's reading, since
    Qloo returns titles, not who is in them."""
    if option.source != "lookalike":
        return "The character is Namesake's AI's reading of the title. "
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
                hook=hook_text(reference),
                copy_text=copy_block(o.name, hook_text(reference), text),
                version_choice=local_choice(o.name, is_local(o, profile)),
                version_label=local_label(is_local(o, profile)),
                entity_id=o.entity_id,
                character=o.character,
                # Only under the title's own name: a character's name in its place
                # would put the app's reading inside Qloo's line.
                audience=audience_line(title, result.audiences.get(o.entity_id))
                if o.entity_id in titles
                else None,
            )
        )
    return NameView(
        value=draft.names[0].name,
        placeholder="",
        options=options,
        audience_note=AUDIENCE_NOTE if any(o.audience for o in options) else "",
    )


# What decision 23's chain rule enforces: listed chains are never suggested; fast food is
# the AI's judgement from a place's description, so said only where the AI picked.
CHAINS_NOTE = "National chains Namesake knows by name are left out."
FAR_NOTE = (
    "National chains Namesake knows by name are left out, and so are places OpenStreetMap "
    f"puts more than {MAX_VENUE_KM} km from the shelter."
)
FAST_FOOD_NOTE = "Namesake's AI is asked to pass over fast food."


def chains_note(profile: LocationProfile) -> str:
    # The distance is said only once a place has a pin to measure (decision 40).
    measured = any(v.latitude is not None for v in profile.venues)
    return (FAR_NOTE if measured else CHAINS_NOTE) + (
        f" {FAST_FOOD_NOTE}" if profile.made_by == "agent" else ""
    )


def empty_venues(profile: LocationProfile, shelter: tuple[float, float] | None = None) -> str:
    """Why no place is suggested, as far as the profile shows it."""
    suitable = [v for v in profile.venues if unsuitable(v) is None]
    if suitable and all(chain_name(v.name) for v in suitable):
        return (
            "Every suitable place Qloo listed here is a national chain Namesake leaves out; "
            "the Why panel names them."
        )
    # The places venue_order would suggest but for the distance: the AI's picks when it
    # picked (decision 23), else every suitable one that is not a chain.
    candidates = [
        v
        for v in suitable
        if not chain_name(v.name) and (profile.made_by != "agent" or v.chosen_reason)
    ]
    if candidates and all(too_far(v, shelter) is not None for v in candidates):
        return (
            f"Every place Namesake would suggest here is more than {MAX_VENUE_KM} km from the "
            "shelter; the Why panel names them."
        )
    if profile.venues and not suitable:
        return "Every place Qloo listed here was screened out; the Why panel names them."
    if profile.venues and profile.made_by == "agent":
        return "Namesake's AI found no place in Qloo's list to suggest for a stand or a flyer."
    return "No venues for this area yet."


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
            f"others can appear. {chains_note(profile)} {shared}"
        )
    if profile.venue_categories is False:
        return (
            f"Qloo's list here, asked for the usual kinds (cafes and breweries, bookshops and "
            f"pet shops, community places), held fewer than {MIN_CATEGORY_VENUES} places, so it "
            f"was asked for places of any kind. {chains_note(profile)} {shared}"
        )
    return f"{chains_note(profile)} {shared}"


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
        f"Qloo's list for this area, asked for the usual kinds (cafes and breweries, bookshops "
        f"and pet shops, community places), held fewer than {MIN_CATEGORY_VENUES} places, so "
        "it was asked for places of any kind."
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
    pets = (
        f"fans of {and_list([e.name for e in titles])}" if titles else "fans of pet-themed titles"
    )
    base = compared_with(profile) or "a baseline"
    cells = []
    # A compared cell's two scores are Namesake's ranks of Qloo's (one_scale), so the label
    # gives each side's place among those cells, never a number that reads as Qloo's.
    both = [c for c in profile.cells if c.lift is not None]

    def place(score: float, side: str) -> str:
        # Tied cells share a range of places, whose middle is the rank lift is taken from,
        # so a label never reads higher on the side whose colour says lower (Codex).
        first = 1 + sum(getattr(o, side) > score for o in both)
        last = sum(getattr(o, side) >= score for o in both)
        return ordinal(first) if first == last else f"joint {ordinal(first)} to {ordinal(last)}"

    for c in profile.cells:
        south, west, north, east = bounds(c.geohash)
        if c.lift is None:
            label = f"Scored for {pets}{shows(c.pet_count)} only; no comparison here."
        elif len(both) == 1:
            label = (
                f"Scored for {pets}{shows(c.pet_count)} and {base}{shows(c.baseline_count)}: "
                "the only such cell, so nothing to compare it with."
            )
        else:
            label = (
                f"{cap(pets)}{shows(c.pet_count)}: {place(c.pet_score, 'pet_score')} "
                f"of these {len(both)} cells; {base}{shows(c.baseline_count)}: "
                f"{place(c.baseline_score, 'baseline_score')}."
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
        (
            f"Warm: fans of pet-themed titles stand out here more than {base}. Cool: less, or "
            "level. Grey: no comparison."
            if any(c.lift is not None for c in cells)
            else "Grey: no cell was scored for both, so there is no comparison here."
        )
        # The circle is drawn on every map with cells, so it is explained on every one;
        # it centres on the visitor's own spot when they picked one.
        + (
            " Circle: around the spot you picked for the shelter."
            if pin
            else " Circle: around the sample shelter the animals are adopted from."
        )
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
            f"fans of pet-themed titles around {location.label} is thin, so the map says little. "
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
    # Both sides are ranked among the same cells (one_scale), so their differences sum to
    # zero: some cells are always warmer than others unless the two order them alike. The
    # count compares parts of the area, never how many fans live anywhere (Flash, Codex).
    where = (
        f"Both sides are ranked among the same cells, so this compares parts of "
        f"{location.label}, not how many fans live there. "
    )
    if not compared or thin:
        # A thin map already says it says little; a count would read as more.
        count = ""
    elif len(compared) == 1:
        count = "Only one cell was scored for both sides, so there is nothing to compare. "
    elif not warm:
        count = f"{cap(pets)} order {some} cells{which} as {base} do. "
    else:
        count = (
            f"{cap(pets)} rank {warm} of {some} {len(compared)} cells{which} higher than "
            f"{base} do. " + where
        )
    # Qloo ranks places in a separate answer from the cells, so a reader should not look
    # for them inside warm cells (the author's question, 20 October).
    numbers = (
        " Numbers: the places to ask, as in the list. Qloo ranks them separately from the "
        "cells, so they need not sit in a warm cell."
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
        tiles=map_tiles(),
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
                # A key, worded as one, so it never reads as a finding when no cell is warm.
                f"Colours: warm where {pets} rank this part of {location.label} higher than "
                f"{base} do; cool where lower, or level; grey where only the pet-themed titles "
                "have a score. Where several "
                "shows scored a cell, their scores are averaged, then ranked among the cells "
                "scored for both, so they compare parts of this area, not other cities."
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


def unsuitable(v: Venue) -> str | None:
    """The screen's word for a venue, as saved or under today's list, so a saved profile
    gets words added since (decision 40)."""
    return v.unsuitable or screen(v.description, v.name)


def too_far(v: Venue, shelter: tuple[float, float] | None) -> float | None:
    """How far a pinned venue is from the shelter's point, when beyond MAX_VENUE_KM."""
    if shelter is None or v.latitude is None or v.longitude is None:
        return None
    km = distance_km(shelter, (v.latitude, v.longitude))
    return km if km > MAX_VENUE_KM else None


def venue_order(
    profile: LocationProfile, shelter: tuple[float, float] | None = None
) -> list[Venue]:
    """The venues to suggest, never screened ones nor national chains (decision 23), nor,
    given the shelter's point (the visitor's pin, else the area's centre), a pinned one too
    far from it (decision 40).

    When the agent built the profile, only the places it chose: its judgement is a
    positive selection, not just the absence of a rejection. The fixed lookup has no
    judgement, so it suggests places that stand out, then the rest.
    """
    suitable = [
        v
        for v in profile.venues
        if unsuitable(v) is None and not chain_name(v.name) and too_far(v, shelter) is None
    ]
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
    ranks among the cells scored for both, for fans of pet-themed titles as a group against
    the comparison shows."""
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
        # The map compares areas, the list places: said, so a place that stands out in the
        # list but sits in a cool cell does not read as a contradiction.
        f"On the map, which compares areas rather than places, OpenStreetMap places it where "
        f"fans of pet-themed titles rank this part of {location.label} {how} {base} do "
        f"({c.lift:+.2f}, worked out from Qloo's maps)."
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
        badge = "Stands out for fans of pet-themed titles"
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


# Fear in a record says busy places are hard (decision 39), unless a negation just before
# it covers it, with any fear words listed after ("not shy at all", "never hides", "not
# shy, nervous or scared"); "not house-trained yet gets scared" still counts.
FEAR = (
    r"(?:hides?|hiding|shy|timid|fearful|nervous|anxious|skittish|scared|frightened"
    r"|stressed|stressful|startles?|startled|overwhelmed|panic(?:s|ked|king)?)"
)
NEGATION = r"(?:\bnot|n't|\bnever|\bno longer)"
# Up to two words between a negation and what it negates ("not at all shy"), never a
# word that turns the sentence ("not aggressive but scared").
BETWEEN = r"(?:(?!(?:but|yet|while|though|although)\b)\w+\s+){0,2}?"
FEAR_WORD = re.compile(rf"\b{FEAR}\b")
# A negation covers the fear words listed after it only in a list that ends in or, and or
# nor ("not nervous or easily startled", "not anxious, fearful, or stressed"); a listed
# word may carry an adverb. A bare comma is read as a new statement ("no longer hides,
# visibly stressed in busy rooms"): when a record is ambiguous, the caution wins, since it
# only quotes the record and suggests a quiet meeting.
ADVERB = r"(?:(?:\w+ly|very|too)\s+)?"
NEGATED_FEAR = re.compile(
    rf"{NEGATION}\s+{BETWEEN}{FEAR}\b"
    rf"(?:(?:\s*,\s*{ADVERB}{FEAR}\b)*\s*,?\s*(?:or|and|nor)\s+{ADVERB}{FEAR}\b)?"
)
# Noise, crowds or busy places say so only beside a difficulty in the same clause ("not
# comfortable in crowds", "dislikes loud noises"), never alone ("has a loud bark",
# "enjoys crowds", "calm in noisy places") nor beside a negated one ("never struggles
# with noise"). A "crowd-pleaser" is not a crowd. Clauses split at commas and at but, yet,
# and, while or though: "calm at home but scared of crowds" is two.
CLAUSES = re.compile(r"[,;.]|\b(?:but|yet|and|while|though|although)\b")
BUSY = re.compile(r"\b(nois(?:y|es?)|loud|crowds?(?!-)|crowded|busy)\b")
STRUGGLE = re.compile(
    r"\b(?:dislikes?|hates?|struggles?|avoids?|cannot|can't|unable to)\b"
    rf"|{NEGATION}\s+{BETWEEN}(?:like|cope|good|comfortable|happy|handle|enjoy)\b"
)
NEGATED_STRUGGLE = re.compile(rf"{NEGATION}\s+{BETWEEN}(?:dislikes?|hates?|struggles?|avoids?)\b")


def outside(found: re.Pattern, negated: re.Pattern, text: str) -> bool:
    """Whether `found` matches somewhere in `text` that no `negated` match covers."""
    spans = [m.span() for m in negated.finditer(text)]
    return any(not any(a <= m.start() < b for a, b in spans) for m in found.finditer(text))


def busy_is_hard(line: str) -> bool:
    return outside(FEAR_WORD, NEGATED_FEAR, line) or any(
        BUSY.search(c) and outside(STRUGGLE, NEGATED_STRUGGLE, c) for c in CLAUSES.split(line)
    )


def busy_events_caution(animal: Animal) -> str | None:
    """The recorded line saying a busy event would be hard for this animal, a fact before
    the temperament, or None. Read from the record only, like the children check."""
    for line in [*animal.facts, animal.temperament or ""]:
        if busy_is_hard(line.lower().replace("’", "'")):
            return line.strip()
    return None


def plan(
    animal: Animal, location: Location, venues: list[Venue], skipped: list[Venue] | None = None
) -> list[PlanItem]:
    caution = busy_events_caution(animal)
    them = OBJECT_PRONOUN.get(animal.sex or "", "them")
    items = [
        PlanItem(
            text="Share the listing through the personal networks of foster carers and volunteers.",
            basis="Research",
        ),
        # Outings and events are the research's in-person channel, but not for an animal
        # whose record says busy places are hard: the record wins (decision 39).
        PlanItem(
            text=f"Skip busy events for this {animal.species}: the record says “{caution}”. "
            f"Let adopters meet {them} somewhere quiet instead.",
            basis="Our suggestion",
        )
        if caution
        else PlanItem(
            text=(
                f"Take the {animal.species} on an outing or to an event in an “Adopt Me” vest."
                if animal.species == "dog"
                else f"Bring the {animal.species} to a meet-and-greet session at an event."
            ),
            basis="Research",
        ),
        PlanItem(
            # Measured in US shelters (adoption-evidence-review.md); said so on every page,
            # since an area may be elsewhere (Barcelona, decision 30).
            text="In US shelter data, adoptions cluster on Saturdays, where shelters open then, "
            "and between 5 and 8 pm: time posts and events for then.",
            basis="Research",
        ),
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
    picks = [v for v in venues[:VENUES_IN_PLAN] if v.chosen_reason]
    picked_by = " (picked by Namesake's AI from Qloo's list)" if picks else ""
    if top:
        items.append(
            PlanItem(
                # The places are Qloo's; which of them to ask is the AI's pick when it gave
                # reasons (an agent profile), said in words beside the Qloo pill.
                text=f"Ask {and_list(top)}{picked_by} about "
                + ("putting up a flyer." if caution else "hosting an adoption event or a flyer."),
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
    return items


# Venues whose name or own Qloo description mentions children: skipped, per animal, when
# the record says the animal is not good with children (decision 2). Whole words, so
# "kid-friendly", "child care" and "Childrens Museum" count; words with other common
# meanings in venue text ("nursery" for plants, "daycare" for dogs, "baby back ribs",
# "youth hostel", a dog park's "play area") are not on the list. A venue with no
# description is judged by its name. Venue names outside the US may be in Spanish or
# Catalan (Barcelona, decision 30), so those languages' plain words count too.
FOR_CHILDREN = re.compile(
    r"\b(child|children|childrens|kid|kids|toddlers?|babies|playgrounds?|playgroups?"
    r"|preschools?|kindergartens?|elementary[- ]schools?|childcare|family[- ]friendly"
    r"|families|storytime|soft[- ]play"
    r"|infantil|infantiles|infantils|niños|niñas|nens|nenes|ludotecas?|ludoteques?"
    r"|familias|famílies)\b"
)


def for_children(name: str | None, description: str | None = None) -> str | None:
    """The word in a venue's name or description that is about children, or None."""
    match = FOR_CHILDREN.search(f"{name or ''}\n{description or ''}".lower())
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
            f"{'them' if len(profile.left_out_titles) > 1 else 'it'} in its pet-themed lists "
            "for this area. "
        )
    elif not profile.titles_confirmed and profile.made_by == "agent":
        text += (
            "None of the titles kept has Qloo's ranking or a place in Qloo's pet-themed lists "
            "for the area, so they are Namesake's AI's own. "
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


def why(
    location: Location, profile: LocationProfile, shelter: tuple[float, float] | None = None
) -> tuple[list[WhyItem], list[WhyItem]]:
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
    chains = [v.name for v in profile.venues if unsuitable(v) is None and chain_name(v.name)]
    if chains:
        reading.append(WhyItem(title="Left out as national chains", detail=and_list(chains) + "."))
    excluded = [f"{v.name} ({unsuitable(v)})" for v in profile.venues if unsuitable(v)]
    if excluded:
        reading.append(WhyItem(title="Left out as event venues", detail=and_list(excluded) + "."))
    # Measured from where the cards measure: the visitor's pin, else the area's centre.
    centre = shelter or (location.latitude, location.longitude)
    far = [
        f"{v.name} ({km:.1f} km)"
        for v in profile.venues
        if unsuitable(v) is None
        and not chain_name(v.name)
        and (km := too_far(v, centre)) is not None
    ]
    if far:
        reading.append(
            WhyItem(
                title=f"Left out as more than {MAX_VENUE_KM} km from the shelter",
                detail=and_list(far) + ".",
            )
        )
    if profile.cells:
        returned.append(
            WhyItem(
                title=f"{len(profile.cells)} map cells within {location.label}",
                detail="Scored by Qloo from 0 to 1, as ranks over the cells it maps for each "
                "title.",
            )
        )
    if any(c.lift is not None for c in profile.cells):
        reading.append(
            WhyItem(
                title="Lift on the map",
                detail="The pet-themed titles' score minus the score for "
                f"{compared_with(profile) or 'the baseline'} in the same cell. Each is averaged "
                "over the shows that scored it, then ranked again among the cells scored for "
                "both, since Qloo ranks each title over its own cells. It is relative: "
                "where in this area fans of pet-themed titles stand out, not how many there are.",
            )
        )
    for call in profile.calls:
        returned.append(
            WhyItem(
                title=f"qloo {call.operation}",
                detail=f"{cap(call.purpose)}: {call.status}, {plural(call.results, 'result')}.",
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


def ai_searches(profile: LocationProfile) -> list[str]:
    """Titles Namesake's AI chose to search Qloo's lists with (find_local_titles) that a
    kept title was found by, in the kept titles' order: the searches behind this result,
    not every search it made (each is in the Why panel's call list). Qloo's pet-tag lists
    are code's own."""
    found = [f for e in profile.pet_entities for f in (e.found_in, e.listed_in) if f]
    return list(dict.fromkeys(f.signal for f in found if not f.by_tags))


def local_touch(
    location: Location,
    profile: LocationProfile,
    listing: ListingResult | None,
    places_shown: int,
) -> str:
    """One plain line under the listing: which parts of this result rest on Qloo's data
    for the area. Counted from the profile and the listing, like qloo_part; the detail
    is in "How Namesake made this" (decision 33). A name counts only when its title has
    Qloo's evidence for the area: ranked here, in Qloo's lists for it, or among what people
    there tend to watch; a lookalike or a title only looked up does not."""
    names = listing.draft.names if listing and listing.draft else []
    backed = [o for o in names if is_local(o, profile)]
    parts = (
        (
            ["the titles behind the names"]
            if backed and len(backed) == len(names)
            else [f"the titles behind {len(backed)} of the {len(names)} names"]
            if backed
            else []
        )
        + ([plural(places_shown, "place") + " to ask"] if places_shown else [])
        + (["the map"] if profile.cells else [])
    )
    if not parts:
        return ""
    return f"From Qloo taste data for {location.label}: {and_list(parts)}."


def qloo_part(
    location: Location,
    profile: LocationProfile,
    listing: ListingResult | None,
    places_shown: int | None = None,
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
            ([f"{len(ranked)} in its ranking here"] if ranked else [])
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
        searches = ai_searches(profile)
        if searches:
            ai.append(f"searched Qloo's lists with {and_list(searches)}")
        own = [e for e in pets if not e.found_in]
        judged = [e for e in pets if e.found_in and bucket(e.verdict) != "kept"]
        # As the cards show them: a screened pick or a listed chain is left out (decision 23).
        # The places the cards show (after the per-animal skip and the display cap), the
        # same count as the process steps; without it, every place the code would suggest.
        picked = (
            len(venue_order(profile, (location.latitude, location.longitude)))
            if places_shown is None
            else places_shown
        )
        if own:
            ai.append(f"proposed {plural(len(own), 'title')} for Qloo to check")
        if judged:
            ai.append(f"judged {plural(len(judged), 'unclear title')}")
        if picked:
            ai.append(f"picked {picked} of the places to ask")
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


def process_steps(
    location: Location,
    profile: LocationProfile,
    listing: ListingResult | None,
    places_shown: int | None = None,
) -> list[ProcessStep]:
    """The three steps behind this story: what each party did for this result, from what
    the profile and the listing record. Nothing is promised that did not happen: a fixed
    lookup, a missing ranking, titles kept without Qloo's evidence or a templated listing
    each say so (decisions 20, 22 and 23). `places_shown` is the number of place cards the
    page shows (after the screens and the per-animal skip); without it, `venue_order`."""
    draft = listing.draft if listing else None
    agent = profile.made_by == "agent"
    pets = profile.pet_entities
    # Every way a title can sit in one of Qloo's lists for the area: its pet-tag lists, a
    # search by one of its titles, or the area's own watched list.
    found = [f for e in pets for f in (e.found_in, e.listed_in) if f]
    facts = ProcessStep(
        title="Start with the facts",
        detail="The shelter's record supplies every sentence of the introduction"
        + (", written by Namesake's AI" if draft else ", built by a fixed template")
        + ". Anything not recorded stays unsaid.",
    )
    returned = []
    if any(f.by_tags for f in found):
        returned.append(
            f"lists of titles people around {location.label} tend to like, asked with its pet tags"
        )
    if any(not f.by_tags for f in found):
        returned.append("lists of what people here who like its titles also tend to like")
    if profile.local_tastes:
        returned.append(f"its list of titles watched around {location.label}")
    if profile.ranked:
        returned.append(f"its ranking of {plural(len(profile.ranked), 'title')} here")
    if profile.venues:
        returned.append(
            f"{plural(len(profile.venues), 'place')} near the shelter for fans of "
            f"{venue_titles(profile)}"
        )
    if profile.cells:
        returned.append(f"{plural(len(profile.cells), 'map cell')} within {location.label}")
    detail = (
        f"Qloo returned {and_list(returned)}."
        if returned
        else f"Qloo returned nothing for {location.label} yet."
    )
    if pets and not profile.ranked:
        detail += " Its ranking of the titles was unavailable."
    context = ProcessStep(title="Add local context", detail=detail)

    did = []
    if any(e.verdict for e in pets):
        did.append(
            "a classifier (TypeSafe's Jev) sorted the titles in Qloo's lists and kept the "
            "clear pet titles"
        )
    checks = []
    if agent:
        # Who proposed a title is where it was found (found_in), as in the strip: listed_in
        # is local evidence, and also marks an AI's own title Qloo listed later.
        own = [e for e in pets if not e.found_in]
        judged = [e for e in pets if e.found_in and bucket(e.verdict) != "kept"]
        # The places the cards show, as the strip counts them: never a pick the code
        # screened out or skipped for this animal.
        picked = (
            len(venue_order(profile, (location.latitude, location.longitude)))
            if places_shown is None
            else places_shown
        )
        ai = []
        if searches := ai_searches(profile):
            ai.append(f"searched Qloo's lists with {and_list(searches)}")
        if judged:
            ai.append(f"judged {plural(len(judged), 'unclear title')}")
        if own:
            ai.append(f"added {plural(len(own), 'title')} of its own")
        if picked:
            ai.append(f"picked {picked} of the places to ask")
        if len(pets) > 1 and profile.order_source != "qloo_rank":
            ai.append("set the order, as Qloo's ranking was unavailable")
        if ai:
            did.append("Namesake's AI " + and_list(ai))
        if profile.titles_confirmed:
            checks.append("kept a title only with Qloo's evidence for the area")
        else:
            # Decision 22: with no evidence for any title, the AI's own stay, and the page
            # says so (as "Who chose" does in the Why panel).
            did.append(
                "none of the titles has Qloo's ranking or a place in Qloo's pet-themed lists "
                "for the area, so Namesake's AI's own titles were kept"
            )
        checks.append("checked that every place came from Qloo")
    else:
        did.append("the titles are a fixed lookup, so no AI judged them")
    if draft:
        did.append("Namesake's AI chose the names and wrote the introduction")
        checks.append("screened the names")
        checks.append("traced every sentence to the record")
    else:
        did.append("the names and the introduction are a fixed template")
        checks.append("added the shelter's confirmed answers to the introduction")
    did.append("code " + and_list(checks))
    interpret = ProcessStep(title="Interpret and check", detail=cap("; ".join(did)) + ".")
    return [facts, context, interpret]


def story_leads(
    animal: Animal,
    listing: ListingResult | None,
    profile: LocationProfile,
    location: Location,
    named_as_set: bool = False,
    option: NameOption | None = None,
) -> tuple[str, str]:
    """The lead under the headline for the local version and for the generic one, each
    true of its version's state: a name backed by local taste data, a name from a title
    Qloo found with no evidence for the area, a lookalike's name (a title Qloo found,
    matched by the AI), a set name for a litter, no local name because the AI's draft
    failed its checks, or no run yet; and the fixed-list generic name. The local lead is
    for `option` when given (the name the volunteer picked), else the draft's first."""
    them = OBJECT_PRONOUN.get(animal.sex or "", "them")
    tail = f"An introduction from the shelter's records. A plan for getting {them} seen."
    draft = listing.draft if listing else None
    reason = (listing.fallback_reason or "") if listing else ""
    if draft is None and "did not pass the checks" in reason:
        # The pipeline's third reason; the other two (no model, no titles) are not a
        # failed draft, and the paper prints the reason itself.
        local = "No local name yet: Namesake's AI's draft did not pass its checks. "
    elif draft is None and reason:
        local = "No local name yet: the templated listing says why. "
    elif draft is None:
        local = "No local name yet: it needs a run of Namesake's AI. "
    elif (option or draft.names[0]).source == "lookalike":
        local = "A name from a lookalike title Qloo found, matched by Namesake's AI. "
    else:
        backed = is_local(option or draft.names[0], profile)
        local = "A name from local taste data" if backed else "A name from a title Qloo found"
        local += ", one of a set for the litter" if named_as_set else ""
        local += ". " if backed else f"; not from Qloo's taste data for {location.label}. "
    generic = "A common pet name from a fixed list, not from Qloo. "
    if named_as_set:
        generic = "A common pet name from a fixed list, not from Qloo and not a set. "
    return local + tail, generic + tail


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
    shelter = pin or (location.latitude, location.longitude)
    every = venue_order(profile, shelter)
    ordered, skipped = venues_for_animal(animal, every)
    named_skips = skipped_shown(every, ordered, skipped)
    shown = ordered[:VENUES_SHOWN]
    # Whether a venue the page would not have shown now takes a slot.
    first = {v.entity_id for v in every[:VENUES_SHOWN]}
    moved_up = any(v.entity_id not in first for v in ordered[:VENUES_SHOWN])
    returned, reading = why(location, profile, shelter)
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
    names = name_view(listing, profile, listing_.text)
    # Each option carries the lead it reads with, so picking it swaps the lead too.
    drafts = listing.draft.names if names.options else []
    for option, drafted in zip(names.options, drafts, strict=True):
        option.lead = story_leads(animal, listing, profile, location, len(named) > 1, drafted)[0]
    return ResultView(
        id=result_id(animal.id, location.id),
        animal=animal_card(animal, image_url),
        location=location_option(location, True),
        litter=litter or [],
        litter_note=("Named as a set with the rest of the litter:" if len(named) > 1 else None),
        qloo_part=qloo_part(location, profile, listing, len(shown)),
        local_touch=local_touch(location, profile, listing, len(shown)),
        local_touch_generic=local_touch(location, profile, None, len(shown)),
        trial=TRIAL,
        trial_link=Link(label="How the trial would work", url=TRIAL_URL),
        name=names,
        listing=listing_,
        chosen_name=listing.draft.names[0].name if listing and listing.draft else None,
        map=map_view(location, profile, pin, shown),
        venues=[venue_view(v, location, profile, n, pin) for n, v in enumerate(shown, start=1)],
        venues_note=venues_note(profile, animal.species),
        venues_empty=(
            f"Every place Namesake would suggest here mentions children, so none is suggested "
            f"for this {animal.species}."
            if every and not ordered
            else empty_venues(profile, shelter)
        ),
        plan_heading=f"Get {OBJECT_PRONOUN.get(animal.sex or '', 'them')} seen",
        plan=plan(animal, location, ordered, named_skips),
        venue_ask="a flyer" if busy_events_caution(animal) else "a flyer or a stand",
        story_heading=f"Let's tell {POSSESSIVE.get(animal.sex or '', 'their')} story.",
        story_lead=story_leads(animal, listing, profile, location, len(named) > 1)[0],
        story_lead_generic=story_leads(animal, listing, profile, location, len(named) > 1)[1],
        introduction_heading=f"{cap(POSSESSIVE.get(animal.sex or '', 'their'))} introduction",
        travel_heading=f"Help {POSSESSIVE.get(animal.sex or '', 'their')} story travel",
        process=process_steps(location, profile, listing, len(shown)),
        run_steps=[
            StepView(kind=s.kind, text=s.text, actor=s.actor, label=actor_label(s.actor))
            for s in (listing.steps if listing else [])
        ],
        run_steps_heading="How this run went, step by step",
        write_label=(
            None
            if listing
            else f"Write {POSSESSIVE.get(animal.sex or '', 'their')} story with Namesake's AI"
        ),
        qloo_returned=returned,
        our_reading=reading,
        notes=profile.notes,
        credits=Credits(
            **({"photos": ADDED_PHOTO_CREDIT} if image_url else {}),
            classifier=CLASSIFIER_CREDIT if any(e.verdict for e in profile.pet_entities) else None,
        ),
    )


# Who did a step, as the step records it (app/agent/steps.py), and its label.
ACTOR_LABELS = [
    ("qloo", "Qloo"),
    ("ai", "Namesake's AI"),
    ("classifier", "Classifier (TypeSafe's Jev)"),
    ("code", "Code"),
]


def actor_label(actor: str) -> str:
    return dict(ACTOR_LABELS).get(actor, "Code")


def build_working_view(
    run, animal: Animal, location: Location, ui_query: str = "", image_url: str | None = None
) -> WorkingView:
    return WorkingView(
        run_id=run.id,
        title=f"Working on the listing for this {animal.species} in {location.label}",
        headline=f"Writing {POSSESSIVE.get(animal.sex or '', 'their')} story…",
        animal=animal_card(animal, image_url),
        credits=Credits(photos=ADDED_PHOTO_CREDIT) if image_url else Credits(),
        location=location_option(location, True),
        events_url=f"/api/runs/{run.id}/events",
        result_url=run.result_url + ui_query,
        steps=[
            StepView(kind=s.kind, text=s.text, actor=s.actor, label=actor_label(s.actor))
            for s in run.log.steps
        ],
        actor_labels=dict(ACTOR_LABELS),
        actor_key=[ActorKey(actor=a, label=label) for a, label in ACTOR_LABELS],
        finished=run.log.finished,
        status=(run.stopped or "Finished.")
        if run.log.finished
        else "Working. Each step appears as it happens.",
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
            f"The version: {variant_label[:1].lower()}{variant_label[1:]}.",
            f"The name, {name}, and where it came from: {name_source}.",
            "Whether you edited the text" + (" (you did)." if edited else " (you did not)."),
            "Not the text itself. This is what a trial of generic against local listings "
            "would compare against adoption dates and returns.",
        ],
        back_url=back_url,
        credits=result.credits,
    )


def build_add_animal_view(
    location_id: str,
    max_facts: int,
    error: str | None = None,
    values: dict[str, str] | None = None,
    area: str = "",
    edit: str = "",
) -> AddAnimalView:
    """With the typed area (`location_id` is TYPED_AREA), its name goes along, and back.
    With `edit`, the form changes that added animal: its record is replaced."""
    typed = location_id == TYPED_AREA
    return AddAnimalView(
        title="Edit your animal" if edit else "Add an animal",
        edit=edit,
        submit_label="Save the changes" if edit else "Add the animal",
        photo_kept_note="Choose none to keep the photo it has, if any." if edit else "",
        location_id=location_id,
        area=area if typed else "",
        back_url=f"/?{urlencode({'area': area} if typed else {'location': location_id})}",
        values=values or {},
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


def area_check_view(area, ui_query: str = "") -> AreaCheckView:
    """The working page's answer when a typed area did not pass (`app.runs.AreaCheck`)."""
    lat, lon = (str(area.pin[0]), str(area.pin[1])) if area.pin else ("", "")
    return AreaCheckView(
        message=area.outcome.message,
        candidates=area.outcome.candidates,
        picked=area.picked,
        pin_lat=lat,
        pin_lon=lon,
        back_url=f"/?{urlencode({'area': area.text})}{ui_query}#shelter",
    )


def build_flyer_view(
    result: ResultView,
    variant: str | None,
    ui_query: str = "",
    name: str | None = None,
    approved: str | None = None,
) -> FlyerView | None:
    """The flyer for one version of a result: the version asked for when it exists, else
    the one the result page opens on; for the local one, the name option chosen on the
    page when `name` is one of them. Built only from the result's own view (decision 35).
    With `approved`, the text the volunteer approved (checked by the caller) replaces the
    drafted listing, for exactly that version and name. None when there is nothing to
    print."""
    versions = {v.variant: v for v in result.listing.versions if v.available}
    if not versions:
        return None
    opened = next((v for v in result.listing.versions if v.selected and v.available), None)
    if approved is not None and (variant or "") not in versions:
        return None
    version = versions.get(variant or "") or opened or next(iter(versions.values()))
    chosen, hook, copy_text = version.name, version.hook, version.copy_text
    label = version.label
    option = next((o for o in result.name.options if o.name == name), None)
    if version.variant == "local" and option is not None:
        chosen, hook, copy_text = option.name, option.hook, option.copy_text
        label = option.version_label
    elif approved is not None and version.variant == "local":
        return None
    if approved is not None:
        copy_text = copy_block(None, hook, approved)
    # The drafted copy text opens with "Meet <name>.", which the flyer shows as its heading.
    # Only that generated line goes: an approved text is printed whole, whatever it says.
    paragraphs = [p for p in copy_text.split("\n\n") if p.strip()]
    if approved is None and paragraphs and paragraphs[0] == f"Meet {chosen}.":
        paragraphs = paragraphs[1:]
    query = urlencode({"animal": result.animal.id, "location": result.location.id})
    other = next((v for v in versions.values() if v.variant != version.variant), None)
    return FlyerView(
        title=f"Meet {chosen}" if chosen else "Meet this animal",
        name=chosen,
        image_url=result.animal.image_url,
        image_alt=result.animal.alt,
        paragraphs=paragraphs,
        version_label=label,
        ask_line=f"Ask the shelter in {result.location.label} about {chosen or 'this animal'}.",
        checklist_note=(
            "Places near the shelter that Qloo returned for fans of pet-themed titles. Each "
            "says what Namesake found when it compared Qloo's list with a baseline, or that "
            f"it could not. Tick each one once you have asked about {result.venue_ask}."
            if result.venues
            # The flyer has no Why panel to point to.
            else result.venues_empty.replace("; the Why panel names them.", ".")
        ),
        # Page 1 is posted alone: it says the shelter is a sample, in a short line.
        sample_line=(
            "The shelter is a sample."
            if result.credits.photos == ADDED_PHOTO_CREDIT
            else result.credits.photos
        ),
        places=[
            FlyerPlace(number=v.number or n, name=v.name, place=v.place, badge=v.badge)
            for n, v in enumerate(result.venues, start=1)
        ],
        other=[item.text for item in result.plan if item.basis != "Qloo"],
        # An approved text is one version's: the other would be a draft.
        other_version=(
            Link(
                label=f"Print the “{other.label}” version instead",
                url=f"/flyer?{query}&variant={other.variant}{ui_query}",
            )
            if other and approved is None
            else None
        ),
        **(
            {
                "print_note": "Page 1 is the flyer to post; page 2 is your checklist. It "
                "prints the listing you approved."
            }
            if approved is not None
            else {}
        ),
        back_url=f"/result?{query}{ui_query}",
        credits=result.credits,
    )
