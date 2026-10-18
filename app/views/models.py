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


class LocationOption(BaseModel):
    id: str
    label: str
    region: str
    latitude: float
    longitude: float
    zoom: int
    shelter_radius_m: float
    selected: bool = False
    # The spot this visitor picked for the shelter, if any, and what the map says about it.
    pin: Pin | None = None
    map_note: str = "The circle marks the area around the fictional shelter, not a real address."


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
    examples_heading: str = "Try an example: these open instantly"
    examples: list[ExampleLink] = []
    locations: list[LocationOption]
    shelter: ShelterBar
    # The caption under the map for the area shown first.
    map_note: str
    location_form: LocationForm = LocationForm()
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
    entity_id: str | None = None
    name: str
    # What Qloo returned: the title and where Qloo ranked it.
    badge: str
    title: str
    # Compact forms for a card: "from <title>" (None when the name is the title or the
    # title is unknown), and the badge with the title unless the badge names it already.
    source_line: str | None = None
    evidence_line: str | None = None
    # Our reading: the reference code built from the agent's pick, and the agent's reason.
    reference: str
    why: str
    # The local version as it reads when this name is chosen.
    hook: str
    copy_text: str


class NameView(BaseModel):
    value: str | None
    placeholder: str
    options: list[NameOptionView] = []


class ListingSentence(BaseModel):
    text: str
    basis: str


class ListingVersion(BaseModel):
    """One of the two versions the volunteer can copy. The bio is the same in both."""

    variant: Literal["generic", "local"]
    label: str
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
    legend: str
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


class PlanItem(BaseModel):
    text: str
    basis: Literal["Research", "Qloo", "Our suggestion"]


class WhyItem(BaseModel):
    entity_id: str | None = None
    title: str
    detail: str


class StepView(BaseModel):
    kind: str
    text: str


class WorkingView(BaseModel):
    run_id: str
    title: str
    animal: AnimalCard
    location: LocationOption
    events_url: str
    result_url: str
    steps: list[StepView]
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


class StoryNameView(BaseModel):
    name: str
    returned: str
    selected: str


class StoryView(BaseModel):
    """Presentation of the recorded facts and process for the story skin."""

    heading: str
    introduction_heading: str
    travel_heading: str
    facts: list[str]
    steps: list[WhyItem]
    still_to_learn: str | None = None
    names: list[StoryNameView] = []


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
    story: StoryView | None = None
    name: NameView
    listing: ListingView
    map: MapView
    venues: list[VenueView]
    plan_heading: str
    plan: list[PlanItem]
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
    """Area names for the location field, or the area around a picked spot."""

    places: list[PlaceOption] = []
    message: str | None = None
