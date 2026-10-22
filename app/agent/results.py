"""What a listing run produces, as saved and shown."""

from pydantic import BaseModel

from app.agent.listing_agent import BioSentence, ListingDraft, Lookalike
from app.agent.steps import Step
from app.audience import TitleAudience

# Raised whenever the listing checks change. A saved result from an older version is
# never shown as it is: app/agent/recheck.py holds it to today's record checks (the bio
# and the names' reasons) and name screen, and anything it cannot recheck is rerun.
CHECKS_VERSION = 14
# What changed since, so which saved drafts a recheck of the record is enough for:
# - 14 words a reference by the character's kind, not its age ("a dog", not "a puppy"),
#   and names a litter only from pet-themed titles (the recheck rebuilds the references
#   and hook from the saved draft; a saved litter keeps its names until the examples
#   are rebuilt);
# - 13 refused a title whose own name does not suit a listing (rechecked with the name
#   screen) and one character offered twice in a draft, and screened a name used as its own
#   title for temperament (both rechecked from the saved draft); widened the
#   bully-type looks (rechecked: the screen reads today's look); screened the hook's
#   character and role, not Qloo's title (rechecked; the saved hook is rebuilt by code);
#   and refused a reference another animal at the shelter has (a check across animals,
#   which a run makes and a recheck of one draft cannot: the examples are rebuilt);
# - 12 refused unflattering names (rechecked with the name screen) and reads a bare "0"
#   as "fact:0" in a bio sentence's keys (a loading change, nothing to recheck);
# - 11 kept the names' reasons to the recorded look, with no temperament; allowed one
#   name per area title while another is unused; and held a lookalike's quoted look to
#   whole phrases (all three rechecked from the record and the saved lookalikes);
# - 10 also counts a title as about real people when the classifier says so (decision
#   20). Titles saved before were never classified, so the rule has nothing to add for
#   them and the recheck holds them to the description check as before;
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
    # Who tends to like each name's title, by Qloo's title ID (app/audience.py). Shown
    # only; added after the run, and by `python -m app.audience` to older listings.
    audiences: dict[str, TitleAudience] = {}
