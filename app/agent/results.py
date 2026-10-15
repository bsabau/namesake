"""What a listing run produces, as saved and shown."""

from pydantic import BaseModel

from app.agent.listing_agent import ListingDraft
from app.agent.steps import Step


class ListingResult(BaseModel):
    animal_id: str
    location_id: str
    # None when the agent's draft failed its checks or the model was unavailable;
    # the page then shows the templated listing and says why.
    draft: ListingDraft | None = None
    fallback_reason: str | None = None
    steps: list[Step] = []
