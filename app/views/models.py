"""View models: everything a screen shows, already worded and in display order.

A UI only renders these. The same objects are served as JSON under `/api/`, so
a different interface can be built on the API alone.
"""

from typing import Literal

from pydantic import BaseModel

PHOTO_CREDIT = "All animals and the shelter are fictional; the photos are AI-generated."
QLOO_CREDIT = "Taste data from the Qloo API. Namesake is not affiliated with or endorsed by Qloo."


class Credits(BaseModel):
    photos: str = PHOTO_CREDIT
    qloo: str = QLOO_CREDIT
    # Shown when a classifier sorted any of the titles on the page (decision 20).
    classifier: str | None = None


class Pin(BaseModel):
    latitude: float
    longitude: float


class MapTiles(BaseModel):
    """The basemap under a map: a Leaflet tile URL template for light and dark mode, its
    attribution and subdomains. Built from the `MAP_TILES_KEY` setting: CARTO's Positron
    and Dark Matter with a key, OpenStreetMap's standard tiles without."""

    url: str
    dark_url: str
    attribution: str
    subdomains: str
    max_zoom: int
    # Where a map goes when the keyed basemap keeps failing (key refused, quota, outage):
    # OpenStreetMap's tiles, with their own attribution.
    fallback_url: str = ""
    fallback_attribution: str = ""
    fallback_max_zoom: int = 19


class VenuePin(BaseModel):
    """A suggested venue on the map, numbered as in the list beside it."""

    number: int
    name: str
    latitude: float
    longitude: float
    # Framed by the map (in a cell or near the shelter); a far pin is drawn, not framed.
    in_view: bool = True


class LocationOption(BaseModel):
    id: str
    label: str
    region: str
    latitude: float
    longitude: float
    zoom: int
    shelter_radius_m: float
    selected: bool = False
    # The area as one phrase: "Park Slope, Brooklyn, New York", or a typed area's name alone.
    place: str = ""
    # The spot this visitor picked for the shelter, if any, and what the map says about it.
    pin: Pin | None = None
    map_note: str = (
        "The circle marks the area around the shelter the animals are adopted from: made up "
        "for this demo, not a real address."
    )


class AnimalCard(BaseModel):
    id: str
    image_url: str
    alt: str
    meta: str
    look: str
    temperament: str
    litter: bool
    featured: bool = False
    badges: list[str] = []
    # What the shelter recorded, as short lines: the observed facts, then the confirmed
    # answers; and the checks still unknown, as labels ("children", "dogs").
    facts: list[str] = []
    unknown: list[str] = []


class LitterCard(BaseModel):
    id: str
    image_url: str
    alt: str
    title: str
    text: str


class ExampleLink(BaseModel):
    label: str
    url: str


class LocationForm(BaseModel):
    action: str = "/locations"
    label: str = "Or type the shelter's area"
    placeholder: str = "A neighbourhood and city, such as “Williamsburg, Brooklyn”"
    hint: str = (
        "Sent to Qloo as typed. Place names only: never a street address. A new area takes "
        "a few minutes the first time."
    )
    map_hint: str = (
        "Or right-click the map (long-press on a phone) where the shelter is: Namesake uses "
        "the area around that spot."
    )
    suggestions_url: str = "/api/places"
    pick_url: str = "/api/places/at"
    # A search on the map that only moves it: no Qloo call, nothing chosen. Shown only
    # when place lookups are on.
    map_search: bool = False
    map_search_label: str = "Find a place on the map"
    map_search_placeholder: str = "A city or area, such as “Barcelona”"
    # A spot picked on the map, carried through Qloo's candidate buttons.
    pin_lat: str = ""
    pin_lon: str = ""
    # After a check: what Qloo said, and its suggestions as buttons.
    message: str | None = None
    value: str = ""
    candidates: list[str] = []


class ShelterBar(BaseModel):
    """The slim bar above the animals: the chosen area, and the panel to change it."""

    heading: str = "Shelter area"
    name: str
    region: str = ""
    chosen: bool = True
    change: str = "Change"
    # Said instead of `change` while no area is chosen.
    choose: str = "Choose an area"
    close: str = "Done"
    panel_heading: str = "Choose the shelter's area"
    # Open when no area is chosen or an area check needs the visitor: the alert, Qloo's
    # candidates and the required choice must be visible.
    open: bool = False


class StartView(BaseModel):
    title: str
    intro: str
    examples_heading: str = "Read a finished story"
    examples: list[ExampleLink] = []
    locations: list[LocationOption]
    shelter: ShelterBar
    # The caption under the map for the area shown first.
    map_note: str
    location_form: LocationForm = LocationForm()
    map_tiles: "MapTiles | None" = None
    animals: list[AnimalCard]
    litters: list[LitterCard]
    add_animal_url: str = "/animals/new"
    add_animal_label: str = "Add your own animal (kept for this visit only)"
    credits: Credits = Credits()


class Question(BaseModel):
    field: str
    label: str


class AddAnimalView(BaseModel):
    title: str = "Add an animal"
    intro: str = (
        "Describe one animal as the shelter has observed it. It is kept in memory for this "
        "visit only, never stored, and gone when you leave or the server restarts. The "
        "listing will say only what you enter here, so leave out anything unconfirmed, and "
        "leave out people's names and personal details."
    )
    action: str = "/animals"
    location_id: str
    # What the visitor entered, kept when the form is refused so only the fix is needed.
    values: dict[str, str] = {}
    species: list[str] = ["dog", "cat"]
    sexes: list[str] = ["female", "male"]
    questions: list[Question]
    answers: list[str] = ["yes", "no", "unknown"]
    max_facts: int
    photo_note: str = (
        "Optional: a JPEG, PNG or WebP photo, up to 3 MB. It is shown back to you only, "
        "never read by a model, and never stored."
    )
    error: str | None = None
    credits: Credits = Credits()


class NameOptionView(BaseModel):
    name: str
    # What Qloo returned: the title, and its evidence for the area (for a lookalike, only
    # that Qloo found the title or offered it among candidates).
    badge: str
    title: str
    # Beside the Qloo pill under the name when this option is picked.
    header_source: str
    # Where the name came from, as an approval records it.
    approved_source: str
    # Our reading: the reference code built from the agent's pick, and the agent's reason
    # (for a lookalike, after the match, which code checked against the record).
    reference: str
    why: str
    # The local version as it reads when this name is chosen, its toggle button included.
    hook: str
    copy_text: str
    version_choice: str
    # What the name refers to, for the approve route's check that no other animal at the
    # shelter is named after it (decision 26): Qloo's title ID and the character.
    entity_id: str = ""
    character: str = ""
    # Who tends to like the title, from Qloo's demographics (app/audience.py); None when
    # Qloo gave no clear lean or was not asked.
    audience: str | None = None


class NameView(BaseModel):
    value: str | None
    placeholder: str
    options: list[NameOptionView] = []
    # What the options' audience lines mean; empty when no option has one.
    audience_note: str = ""


class ListingSentence(BaseModel):
    text: str
    basis: str


class ListingVersion(BaseModel):
    """One of the two versions the volunteer can copy. The bio is the same in both."""

    variant: Literal["generic", "local"]
    label: str
    # The toggle's text: the label and the version's name, so both names show at a glance.
    choice: str
    available: bool
    name: str | None
    name_source: str
    # The local version adds this one line; the generic version has none.
    hook: str | None = None
    copy_text: str
    note: str | None = None
    selected: bool = False


class ListingView(BaseModel):
    heading: str
    text: str
    sentences: list[ListingSentence]
    word_count: int
    # Set when the recorded facts cannot fill a full listing; the text is never padded.
    short_note: str | None = None
    left_out: list[str]
    versions: list[ListingVersion]
    toggle_note: str
    # Why the page shows the templated listing instead of the agent's.
    fallback_note: str | None = None
    # Set when this visitor asked for a refined version; only they see it.
    refined_note: str | None = None
    written_by: str
    # Phrases every edit must keep: cautions are never softened or dropped.
    must_keep: list[str] = []


class MapCell(BaseModel):
    geohash: str
    south: float
    west: float
    north: float
    east: float
    lift: float | None
    label: str


class MapView(BaseModel):
    latitude: float
    longitude: float
    zoom: int
    shelter_radius_m: float
    pin: Pin | None = None
    cells: list[MapCell]
    venues: list[VenuePin] = []
    legend: str
    tiles: MapTiles | None = None
    # A short key drawn on the map itself; the legend under it says the rest.
    note_heading: str = "What the colours mean"
    note: str | None = None
    empty_message: str | None = None


class VenueView(BaseModel):
    name: str
    place: str
    description: str | None
    stands_out: bool
    badge: str
    # Qloo's rank for this place, plainly: "2nd of 15", and where that sits in the list.
    rank: str
    rank_band: Literal["top", "middle", "bottom"]
    rank_note: str
    evidence: str
    # The agent's reason for suggesting it: our reading, shown apart from the evidence.
    chosen: bool = False
    reason: str | None = None
    # Its number on the map, and where it sits: the cell's reading and the distance from
    # the shelter (None when OpenStreetMap had no match for it).
    number: int = 0
    where: str | None = None
    distance: str | None = None


class PlanItem(BaseModel):
    text: str
    basis: Literal["Research", "Qloo", "Our suggestion"]


class WhyItem(BaseModel):
    title: str
    detail: str


class ProcessStep(BaseModel):
    """One of the three steps behind a result, worded from what the profile and the
    listing record: the facts, Qloo's local context, the interpretation and the checks."""

    title: str
    detail: str


class StepView(BaseModel):
    kind: str
    text: str
    # Who did it, as the step records it: "qloo" (its calls and answers), "ai" (a decision
    # of Namesake's AI), "classifier" (TypeSafe's Jev) or "code" (the run's own steps).
    actor: str = "code"
    label: str = "Code"


class ActorKey(BaseModel):
    actor: str
    label: str


class WorkingView(BaseModel):
    run_id: str
    title: str
    # The story skin's headline ("Writing her story…", the pronoun from the record).
    headline: str = ""
    animal: AnimalCard
    location: LocationOption
    events_url: str
    result_url: str
    steps: list[StepView]
    # Each actor's label, for the key and for steps that arrive over the live stream.
    actor_labels: dict[str, str] = {}
    actor_key: list[ActorKey] = []
    finished: bool
    # A sign of life between steps, so a long model call never looks stuck: words to
    # cycle, and the time since the last step ("0:42 since the last step").
    busy_words: list[str] = [
        "Thinking",
        "Pondering",
        "Ruminating",
        "Weighing the options",
        "Mulling it over",
        "Still at it",
    ]
    busy_since: str = "since the last step"
    # Seconds since the last step when the page was built, so a reload keeps counting.
    seconds_since_step: int = 0
    credits: Credits = Credits()


class QlooPart(BaseModel):
    """One line each, near the top of the result: what Qloo returned for this result, and
    what Namesake's AI did with it, kept apart (provenance). The UI labels them "Qloo:"
    and "Namesake's AI:"."""

    qloo: str
    ai: str


class ResultView(BaseModel):
    id: str
    animal: AnimalCard
    location: LocationOption
    approve_url: str = "/approve"
    refine_url: str = "/refine"
    refine_placeholder: str = "Ask for a change, such as “shorter names” or “less childish”"
    # Other members of a litter named as a set, with links to their results.
    litter: list["LitterMateView"] = []
    litter_note: str | None = None
    # Set when an approval was refused, with the volunteer's edit kept.
    approve_error: str | None = None
    edited_text: str | None = None
    # The local name option picked; the first option unless the volunteer chose another.
    chosen_name: str | None = None
    # What Qloo returned and what the AI did, legible in one screenshot.
    qloo_part: QlooPart | None = None
    name: NameView
    listing: ListingView
    map: MapView
    venues: list[VenueView]
    # Our framing of the list: which kinds of place were asked for, and why; that the
    # places are the area's, the same for every animal of that species there.
    venues_note: str | None = None
    # Shown in place of the venue list when it is empty.
    venues_empty: str = "No venues for this area yet."
    plan_heading: str
    plan: list[PlanItem]
    # Headings worded with the animal's pronoun ("Let's tell her story.", "Her
    # introduction", "Help her story travel"), for a skin that tells the result as a story.
    story_heading: str = ""
    # The lead under the headline, for the local version and for the generic one, each
    # true of that version (a Qloo name, a fixed-list name, or no local name yet).
    story_lead: str = ""
    story_lead_generic: str = ""
    introduction_heading: str = ""
    travel_heading: str = ""
    # "Behind this story": three steps from the actual profile and listing (decision 24).
    process: list[ProcessStep] = []
    # The saved run's own step log, each step marked by who did it, as the working page
    # showed it: judges who open a saved result never see a live run (decision 27).
    run_steps: list[StepView] = []
    run_steps_heading: str = ""
    # With no listing yet for this animal here: the button that starts a run, and what it
    # runs (the animal, or for a litter member the litter, named as a set).
    write_label: str | None = None
    write_animal: str = ""
    qloo_returned: list[WhyItem]
    our_reading: list[WhyItem]
    notes: list[str]
    credits: Credits = Credits()


class LitterMateView(BaseModel):
    name: str
    url: str
    current: bool = False


class ApprovedView(BaseModel):
    """The copy-ready listing after a volunteer approves it."""

    id: str
    title: str
    animal: AnimalCard
    location: LocationOption
    variant_label: str
    copy_text: str
    recorded: list[str]
    back_url: str
    credits: Credits = Credits()


class NoticeView(BaseModel):
    """A refusal or a gap, worded for the visitor, with where to go next."""

    title: str
    message: str
    links: list[tuple[str, str]] = []
    credits: Credits = Credits()


ResultView.model_rebuild()


class PlaceOption(BaseModel):
    label: str
    latitude: float
    longitude: float


class PlacesView(BaseModel):
    """Area names for the location field and the map search, or the area around a
    picked spot."""

    places: list[PlaceOption] = []
    message: str | None = None
