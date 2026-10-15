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


class LocationOption(BaseModel):
    id: str
    label: str
    region: str
    latitude: float
    longitude: float
    zoom: int
    selected: bool = False


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


class StartView(BaseModel):
    title: str
    intro: str
    locations: list[LocationOption]
    animals: list[AnimalCard]
    litters: list[LitterCard]
    credits: Credits = Credits()


class NameView(BaseModel):
    value: str | None
    placeholder: str


class ListingSentence(BaseModel):
    text: str
    basis: str


class ListingView(BaseModel):
    heading: str
    text: str
    sentences: list[ListingSentence]
    word_count: int
    left_out: list[str]
    copy_text: str


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
    cells: list[MapCell]
    legend: str
    empty_message: str | None = None


class VenueView(BaseModel):
    name: str
    place: str
    description: str | None
    stands_out: bool
    badge: str
    evidence: str


class PlanItem(BaseModel):
    text: str
    basis: Literal["Research", "Qloo", "Our suggestion"]


class WhyItem(BaseModel):
    title: str
    detail: str


class ResultView(BaseModel):
    id: str
    animal: AnimalCard
    location: LocationOption
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
