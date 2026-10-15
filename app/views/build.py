"""Build view models from domain objects. All user-facing wording lives here."""

import re

from app.agent.results import ListingResult
from app.animals import Animal, LitterPhoto, Roster
from app.listing import CHECK_SENTENCES, MIN_WORDS, templated_listing
from app.locations import Location
from app.profile import LocationProfile, Venue
from app.qloo.geohash import bounds
from app.views.models import (
    AnimalCard,
    ListingSentence,
    ListingView,
    LitterCard,
    LocationOption,
    MapCell,
    MapView,
    NameOptionView,
    NameView,
    PlanItem,
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


def animal_card(animal: Animal) -> AnimalCard:
    return AnimalCard(
        id=animal.id,
        image_url=photo_url(animal.image),
        alt=animal.look,
        meta=" · ".join(x for x in [animal.group.capitalize(), animal.sex, animal.age] if x),
        look=animal.look[:1].upper() + animal.look[1:],
        temperament=animal.temperament[:1].upper() + animal.temperament[1:],
        litter=animal.litter is not None,
        featured=animal.id == FEATURED,
        badges=(["litter"] if animal.litter else [])
        + (["long stay"] if any("months" in h for h in animal.history) else []),
    )


def litter_card(litter: LitterPhoto) -> LitterCard:
    return LitterCard(
        id=litter.id,
        image_url=photo_url(litter.image),
        alt=f"{len(litter.members)} kittens from the same litter",
        title="The whole litter",
        text=f"{len(litter.members)} kittens, named together as a set.",
    )


def build_start_view(roster: Roster, locations: list[Location], selected_id: str) -> StartView:
    animals = sorted(roster.animals, key=lambda a: a.id != FEATURED)
    return StartView(
        title="Write an adoption listing",
        intro=(
            "Pick the shelter's area and an animal. Namesake drafts a plain listing from the "
            "facts the shelter recorded, and a plan for getting the animal seen, using Qloo "
            "taste data about pet-themed shows near the shelter."
        ),
        locations=[location_option(loc, loc.id == selected_id) for loc in locations],
        animals=[animal_card(a) for a in animals],
        litters=[litter_card(lit) for lit in roster.litters],
    )


def basis_label(key: str) -> str:
    if key == "temperament":
        return "Temperament, as staff describe it"
    if key == "look":
        return "Recorded look"
    return "Recorded fact" if key.startswith("fact:") else "Confirmed by the shelter"


def listing_view(animal: Animal, result: ListingResult | None = None) -> ListingView:
    draft = result.draft if result else None
    if draft is not None:
        bio = [(s.text, s.facts) for s in draft.bio]
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
    name = draft.names[0].name if draft else None
    hook = draft.hook.text if draft else None
    copy_text = "\n\n".join(x for x in [f"Meet {name}." if name else None, hook, text] if x)
    return ListingView(
        heading=f"Meet {name}" if name else f"Adoptable {animal.species}",
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
        copy_text=copy_text,
        hook=hook,
        fallback_note=result.fallback_reason if result else None,
        written_by=written_by,
    )


def name_view(result: ListingResult | None, profile: LocationProfile) -> NameView:
    draft = result.draft if result else None
    if draft is None:
        return NameView(
            value=None,
            placeholder="No name yet: the agent's name options appear after a run.",
        )
    titles = {e.id: e.name for e in profile.pet_entities + profile.local_tastes}
    return NameView(
        value=draft.names[0].name,
        placeholder="",
        options=[
            NameOptionView(
                name=o.name,
                badge="Pet-themed title, strong here" if o.source == "pet" else "Watched locally",
                reference=o.reference,
                title=titles.get(o.entity_id, o.reference),
                why=o.why,
            )
            for o in draft.names
        ],
    )


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


def venue_order(venues: list[Venue]) -> list[Venue]:
    """The agent's picks first, then places that stand out, then the rest; never screened ones."""
    suitable = [v for v in venues if v.unsuitable is None and v.rejected_reason is None]
    return sorted(suitable, key=lambda v: (v.chosen_reason is None, not v.distinctive, v.rank))


def venue_view(v: Venue, location: Location, profile: LocationProfile) -> VenueView:
    pets = and_list([e.name for e in profile.pet_entities])
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
) -> ResultView:
    ordered = venue_order(profile.venues)
    returned, reading = why(location, profile)
    return ResultView(
        id=result_id(animal.id, location.id),
        animal=animal_card(animal),
        location=location_option(location, True),
        name=name_view(listing, profile),
        listing=listing_view(animal, listing),
        map=map_view(location, profile),
        venues=[venue_view(v, location, profile) for v in ordered[:VENUES_SHOWN]],
        plan_heading=f"Get {OBJECT_PRONOUN.get(animal.sex or '', 'them')} seen",
        plan=plan(animal, location, ordered),
        qloo_returned=returned,
        our_reading=reading,
        notes=profile.notes,
    )


def build_working_view(run, animal: Animal, location: Location, ui_query: str = "") -> WorkingView:
    return WorkingView(
        run_id=run.id,
        title=f"Working on the listing for this {animal.species} in {location.label}",
        animal=animal_card(animal),
        location=location_option(location, True),
        events_url=f"/api/runs/{run.id}/events",
        result_url=run.result_url + ui_query,
        steps=[StepView(kind=s.kind, text=s.text) for s in run.log.steps],
        finished=run.log.finished,
    )
