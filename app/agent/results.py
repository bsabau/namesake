"""What a listing run produces, as saved and shown."""

from pydantic import BaseModel

from app.agent.listing_agent import BioSentence, ListingDraft, Lookalike
from app.agent.steps import Step

# Raised whenever the listing checks change; saved results from an older version are
# rerun instead of shown, since they were never held to the current rules.
CHECKS_VERSION = 7
# Versions 6 and 7 changed only the checks on lookalike names (decision 14), so a
# listing without one still holds from version 5 on; one with a lookalike name must be
# current.
PLAIN_LISTINGS_FROM = 5


class ListingResult(BaseModel):
    animal_id: str
    location_id: str
    checks_version: int = 0
    # None when the agent's draft failed its checks or the model was unavailable;
    # the page then shows the templated listing and says why.
    draft: ListingDraft | None = None
    # The bio as shown: the agent's sentences, then the confirmed checks added by code.
    bio: list[BioSentence] = []
    # Built by code from each name's character, role and Qloo title, in name order.
    references: list[str] = []
    # Built by code from the first name's reference; None without a draft.
    hook: str | None = None
    # Titles the agent looked up for this animal's look, as Qloo returned them.
    lookalikes: list[Lookalike] = []
    fallback_reason: str | None = None
    steps: list[Step] = []
