"""Build view models from domain objects. All user-facing wording lives here."""

import re

from app.agent.results import ListingResult
from app.animals import Animal, LitterPhoto, Roster
from app.listing import CHECK_SENTENCES, MIN_WORDS, cautions, templated_listing
from app.locations import Location
from app.profile import LocationProfile, Venue
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
    PlanItem,
    Question,
    ResultView,
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


def location_option(location: Location, selected: bool = False) -> LocationOption:
    return LocationOption(
        id=location.id,
        label=location.label,
        region=location.region,
        latitude=location.latitude,
        longitude=location.longitude,
        zoom=location.zoom,
        shelter_radius_m=shelter_radius(location),
        selected=selected,
    )


def shelter_radius(location: Location) -> float:
    """The circle around the fictional shelter, in metres: wider for a city."""
    return 800 * 2 ** (14 - location.zoom)


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
) -> StartView:
    animals = sorted(roster.animals, key=lambda a: a.id != FEATURED)
    return StartView(
        examples=examples or [],
        title="Write an adoption listing",
        intro=(
            "Pick the shelter's area and an animal. Namesake drafts a plain listing from the "
            "facts the shelter recorded, and a plan for getting the animal seen, using Qloo "
            "taste data about pet-themed shows near the shelter."
        ),
        locations=[location_option(loc, loc.id == selected_id) for loc in locations],
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
        written_by = "Written by the agent from the shelter's records, then checked by code."
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
                name_badge(draft.names[0].source, draft.names[0].entity_id, profile)
                if draft
                else ""
            ),
            hook=local_hook,
            copy_text=copy_block(local_name, local_hook, text) if draft else "",
            note=None if draft else "No local version yet: it needs the agent's name options.",
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


def name_badge(source: str, entity_id: str, profile: LocationProfile) -> str:
    """Claim local strength only where Qloo's ranking for this area says so."""
    if source == "local":
        return "Watched locally"
    if entity_id in profile.ranked:
        place = profile.ranked.index(entity_id) + 1
        return f"Pet-themed title, ranked {ordinal(place)} of {len(profile.ranked)} here by Qloo"
    return "Pet-themed title"


def name_view(result: ListingResult | None, profile: LocationProfile, text: str) -> NameView:
    draft = result.draft if result else None
    if draft is None:
        return NameView(
            value=None,
            placeholder="No name yet: the agent's name options appear after a run.",
        )
    titles = {e.id: e.name for e in profile.pet_entities + profile.local_tastes}
    refs = result.references
    options = []
    for i, o in enumerate(draft.names):
        reference = refs[i] if i < len(refs) else o.character
        options.append(
            NameOptionView(
                name=o.name,
                badge=name_badge(o.source, o.entity_id, profile),
                title=titles.get(o.entity_id, o.character),
                reference=reference,
                why=o.why,
                hook=f"Named after {reference}.",
                copy_text=copy_block(o.name, f"Named after {reference}.", text),
            )
        )
    return NameView(value=draft.names[0].name, placeholder="", options=options)


def map_view(location: Location, profile: LocationProfile) -> MapView:
    pet = profile.pet_entities[0].name if profile.pet_entities else "the pet-themed show"
    base = profile.baseline.name if profile.baseline else "the baseline show"
    cells = []
    for c in profile.cells:
        south, west, north, east = bounds(c.geohash)
        if c.lift is None:
            label = f"Scored for fans of {pet} only; {base} has no score here."
        else:
            label = f"Fans of {pet}: {c.pet_score:.2f}; fans of {base}: {c.baseline_score:.2f}."
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
    return MapView(
        latitude=location.latitude,
        longitude=location.longitude,
        zoom=location.zoom,
        shelter_radius_m=shelter_radius(location),
        cells=cells,
        legend=(
            f"Warm cells: fans of {pet} rank this part of {location.label} higher than fans of "
            f"{base} do. Cool cells: lower. Grey: only {pet}'s fans have a score. Scores are "
            "ranks within the area, so they compare places here, not with other cities."
        ),
        empty_message=None if cells else "No map data for this area yet.",
    )


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
    base = profile.baseline.name if profile.baseline else None
    total = len(profile.venues)
    evidence = (
        f"Ranked {ordinal(v.rank)} of {total} places near {location.label} for fans of {pets}"
    )
    if not v.compared or base is None:
        evidence += "; not compared with a baseline."
        badge = "Not compared"
    elif v.distinctive:
        evidence += f"; not among the {profile.baseline_venue_count} places for fans of {base}."
        badge = "Stands out for pet-show fans"
    else:
        evidence += f"; also {ordinal(v.baseline_rank)} for fans of {base}."
        badge = "Popular nearby generally"
    return VenueView(
        name=v.name,
        place=", ".join(x for x in [v.neighbourhood, v.address] if x),
        description=sentences(v.description) or None,
        stands_out=v.distinctive,
        badge=badge,
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


def why(location: Location, profile: LocationProfile) -> tuple[list[WhyItem], list[WhyItem]]:
    returned, reading = [], []
    for e in profile.pet_entities + ([profile.baseline] if profile.baseline else []):
        kind = e.type.removeprefix("urn:entity:").replace("_", " ")
        if e.resolution == "chosen":
            returned.append(
                WhyItem(
                    title=f"{e.name} ({kind})",
                    detail=f"Qloo has {e.alternatives + 1} entries with this name. "
                    + sentences(e.description),
                )
            )
        else:
            returned.append(WhyItem(title=f"{e.name} ({kind})", detail=sentences(e.description)))
    for e in profile.pet_entities:
        detail = f"A pet-themed pick: {e.why.rstrip('.')}."
        if e.choice_reason:
            detail += f" {cap(e.choice_reason.rstrip('.'))}."
        reading.append(WhyItem(title=f"Why {e.name}", detail=detail))
    if profile.made_by == "agent":
        reading.append(
            WhyItem(
                title="Who chose",
                detail="The agent proposed the titles, settled ambiguous names and picked the "
                "venues; code checked that each came from Qloo. "
                + (
                    "The order of the titles is Qloo's ranking for this area."
                    if profile.order_source == "qloo_rank"
                    else "Qloo's ranking was unavailable, so the order is the agent's."
                ),
            )
        )
    if profile.baseline:
        reading.append(
            WhyItem(
                title=f"Why compare with {profile.baseline.name}",
                detail=f"{cap(profile.baseline.why)}. Places and map cells that rank high for "
                "both are popular generally, not because of pets.",
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
                    f"; {shared} of them also rank for fans of {profile.baseline.name}."
                    if profile.baseline and profile.venues[0].compared
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
        reading.append(
            WhyItem(
                title="Lift on the map",
                detail="The pet show's score minus the baseline's score in the same cell. It is "
                "relative: where in this area pet-show fans stand out, not how many there are.",
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
) -> ResultView:
    ordered = venue_order(profile)
    returned, reading = why(location, profile)
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
        map=map_view(location, profile),
        venues=[venue_view(v, location, profile) for v in ordered[:VENUES_SHOWN]],
        plan_heading=f"Get {OBJECT_PRONOUN.get(animal.sex or '', 'them')} seen",
        plan=plan(animal, location, ordered),
        qloo_returned=returned,
        our_reading=reading,
        notes=profile.notes,
        credits=Credits(photos=ADDED_PHOTO_CREDIT) if image_url else Credits(),
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
