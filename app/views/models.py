"""View models: everything a screen shows, already worded and in display order.

A UI only renders these. The same objects are served as JSON under `/api/`, so
a different interface can be built on the API alone.
"""

from typing import Literal

from pydantic import BaseModel

PHOTO_CREDIT = "A sample shelter: the animals are fictional and their photos AI-generated."
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
        "The circle marks the area around the sample shelter the animals are adopted from, "
        "not a real address."
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
    # Added by this visitor: it can be edited or removed.
    own: bool = False
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


# The `location` value of the area typed in the panel, beside the presets' IDs.
TYPED_AREA = "typed"


class LocationForm(BaseModel):
    """The typed area: one more choice beside the presets, checked with Qloo as the run's
    first step once an animal is picked (decision 32)."""

    typed_value: str = TYPED_AREA
    label: str = "Another area"
    field_label: str = "The shelter's area, as a neighbourhood and city"
    placeholder: str = "A neighbourhood and city, such as “Williamsburg, Brooklyn”"
    hint: str = (
        "Checked with Qloo, as typed, when you pick an animal. Place names only: never a "
        "street address. A new area takes a few minutes the first time."
    )
    # Said in the map's popup once a spot's area is chosen.
    picked_note: str = "Chosen. Now pick an animal, and Qloo checks this area first."
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
    # The typed area is the choice (back from a check, or a refused name).
    typed: bool = False
    # A name the field refuses (digits, say), said before any run.
    message: str | None = None
    value: str = ""


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
    # Open when no area is chosen, or the typed area needs the visitor (a name the field
    # refused, or back from a check that did not pass): the alert and the choice show.
    open: bool = False


class Link(BaseModel):
    label: str
    url: str


class StartView(BaseModel):
    title: str
    intro: str
    # The problem in one line, and the research it rests on, so the start page shows why
    # the listing is plain and the names screened (decision 33).
    problem: str = ""
    problem_link: Link | None = None
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
    add_animal_label: str = "Add your own animal"
    # The visitor's own animals, before the samples (story), and the workspace that keeps
    # them: one line, and the link that opens it in another browser (decision 34).
    your_heading: str = "Your animals"
    your_animals: list[AnimalCard] = []
    sample_heading: str = "Or try a sample animal"
    sample_animals: list[AnimalCard] = []
    workspace_note: str = ""
    workspace_link: str = ""
    workspace_link_label: str = "Link to this workspace"
    credits: Credits = Credits()


class Question(BaseModel):
    field: str
    label: str


class AddAnimalView(BaseModel):
    title: str = "Add an animal"
    intro: str = (
        "Describe one animal as the shelter has observed it. It is kept in your workspace "
        "for 7 days after your last visit, and anyone with the workspace's link can open "
        "it. The listing will say only what you enter here, so leave out anything "
        "unconfirmed, and leave out people's names and personal details."
    )
    action: str = "/animals"
    # The added animal being edited, if any: its record is replaced, its listings dropped.
    edit: str = ""
    submit_label: str = "Add the animal"
    # Under the photo field when editing an animal that has one.
    photo_kept_note: str = ""
    location_id: str
    # The typed area's name, when it is the choice, and the way back to the animals.
    area: str = ""
    back_url: str
    # What the visitor entered, kept when the form is refused so only the fix is needed.
    values: dict[str, str] = {}
    species: list[str] = ["dog", "cat"]
    sexes: list[str] = ["female", "male"]
    questions: list[Question]
    answers: list[str] = ["yes", "no", "unknown"]
    max_facts: int
    photo_note: str = (
        "Optional: a JPEG, PNG or WebP photo, up to 3 MB. It is kept with your workspace, "
        "shown to whoever opens it, and never read by a model."
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
    # The flyer for the local version with this name (decision 35).
    flyer_url: str = ""
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


class AreaCheckView(BaseModel):
    """A typed area Qloo did not pass, on the working page: what it said, its candidates
    as buttons that start the same animal again, and a way back to change the area."""

    status: str = "Stopped at the area check, so no listing was written."
    message: str
    candidates: list[str] = []
    picked: str
    typed_value: str = TYPED_AREA
    # The visitor's spot, carried in the form (never a URL) so a candidate keeps it.
    pin_lat: str = ""
    pin_lon: str = ""
    back_url: str
    back_label: str = "Change the area"


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
    # A typed area that did not pass its check: the run ended there.
    area: AreaCheckView | None = None


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
    refine_placeholder: str = "Ask for a change, such as “shorter sentences” or “other names”"
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
    # One plain line under the listing: what in this result comes from Qloo's data for
    # the area. The detail is in "How Namesake made this" (decision 33).
    local_touch: str = ""
    # The same line for the generic version, whose names are not Qloo's: the places and
    # the map only.
    local_touch_generic: str = ""
    # The trial the local version would need, in one line, with the README's design.
    trial: str = ""
    trial_link: Link | None = None
    # A printable flyer and checklist for each version of this result (decision 35); the
    # local one only when that version exists.
    flyer_generic_url: str = ""
    flyer_local_url: str = ""
    flyer_label: str = "Print a flyer"
    how_heading: str = "How Namesake made this"
    how_lead: str = "What came from Qloo, what Namesake's AI did with it, and what code checked."
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
    # "How Namesake made this": three steps from the actual profile and listing (decision 24).
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
    # Posted to /flyer with the approved text, which is not kept anywhere.
    flyer_label: str = "Print a flyer with this text"
    flyer_fields: dict[str, str] = {}
    credits: Credits = Credits()


class NoticeView(BaseModel):
    """A refusal or a gap, worded for the visitor, with where to go next."""

    title: str
    message: str
    links: list[tuple[str, str]] = []
    # One button that posts to `action_url`, for a step the visitor must confirm.
    action_url: str = ""
    action_label: str = ""
    # Sent with the button, as hidden fields.
    action_fields: dict[str, str] = {}
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


class FlyerPlace(BaseModel):
    number: int
    name: str
    place: str
    # Namesake's comparison of Qloo's two lists for the place, as its card shows it.
    badge: str = ""


class FlyerView(BaseModel):
    """A printable page: the flyer to post, then the volunteer's checklist (decision 35).
    The listing, names, places and plan are the result page's own, except that a flyer
    printed from the approval page carries the text just approved; only the lines that
    frame them (who to ask, how to use the checklist) are new."""

    title: str
    name: str | None
    image_url: str
    image_alt: str
    # The version as the volunteer would copy it, after its "Meet <name>." line.
    paragraphs: list[str]
    version_label: str
    ask_line: str
    sample_line: str = ""
    checklist_heading: str = "Where to take this flyer"
    checklist_note: str = ""
    places: list[FlyerPlace] = []
    other_heading: str = "Other ways to help"
    other: list[str] = []
    # A line the volunteer types on the page for the shelter's phone, email or website:
    # printed under the ask line, never sent or saved (no form holds it).
    contact_label: str = "Shelter contact, printed under that line"
    contact_placeholder: str = "Phone, email or website"
    print_label: str = "Print this page"
    print_note: str = (
        "Page 1 is the flyer to post; page 2 is your checklist. It prints the drafted "
        "listing; to print your edit, approve it, then print from the approval page."
    )
    other_version: Link | None = None
    back_url: str
    back_label: str = "Back to the result"
    credits: Credits = Credits()
