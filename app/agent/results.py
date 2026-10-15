"""What a listing run produces, as saved and shown."""

from pydantic import BaseModel

from app.agent.listing_agent import BioSentence, ListingDraft
from app.agent.steps import Step


class ListingResult(BaseModel):
    animal_id: str
    location_id: str
    # None when the agent's draft failed its checks or the model was unavailable;
    # the page then shows the templated listing and says why.
    draft: ListingDraft | None = None
    # The bio as shown: the agent's sentences, then the confirmed checks added by code.
    bio: list[BioSentence] = []
    # Built by code from the first name's reference; None without a draft.
    hook: str | None = None
    fallback_reason: str | None = None
    steps: list[Step] = []
