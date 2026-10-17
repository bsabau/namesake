"""What a listing run produces, as saved and shown."""

from pydantic import BaseModel

from app.agent.listing_agent import BioSentence, ListingDraft, Lookalike
from app.agent.steps import Step

# Raised whenever the listing checks change. A saved result from an older version is
# never shown as it is: app/agent/recheck.py holds it to today's record checks (the bio
# and the names' reasons) and name screen, and anything it cannot recheck is rerun.
CHECKS_VERSION = 10
# What changed since, so which saved drafts a recheck of the record is enough for:
# - 10 also counts a title as about real people when the classifier says so (decision
#   20); saved titles from before have no classifier answer, so the recheck covers it;
# - 9 screened names for real people and identity-coded references, in the name and the
#   title it comes from (rechecked with the saved profile's titles);
# - 8 allowed "puppy" and "kitten" only for an animal under a year (bio and reasons);
# - 6 and 7 changed only the checks on lookalike names (decision 14).
# Raise these floors when a change touches any other check.
PLAIN_LISTINGS_FROM = 5
LOOKALIKE_LISTINGS_FROM = 7


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
