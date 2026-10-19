"""Who tends to like each name's title: Qloo's audience demographics (decision 31).

A fixed call per title after a listing run (`audience_demographics` with the title's
ID), saved on the listing and shown beside each name option. It describes the title's
audience across all of Qloo's data, never the area or a person, and plays no part in
choosing names: it is there for the volunteer to read.

Qloo returns, per age band and gender, a skew from -1 to +1 against its average
audience. Only leans of LEAN or more are shown; a title with none shows nothing.

    python -m app.audience [--min-interval 10]

fills it in for saved listings from before it existed, once, on the host.
"""

import argparse
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.agent.steps import StepLog
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss

if TYPE_CHECKING:
    from app.agent.results import ListingResult

logger = logging.getLogger(__name__)

OPERATION = "audience_demographics"
LEAN = 0.15
AGE_BANDS = {
    "24_and_younger": "24 and under",
    "25_to_29": "25 to 29",
    "30_to_34": "30 to 34",
    "35_to_44": "35 to 44",
    "45_to_54": "45 to 54",
    "55_and_older": "55 and over",
}
GENDERS = {"female": "women", "male": "men"}
NOTE = (
    "Who tends to like each title is Qloo's skew by age and gender against its average "
    "audience, from −1 to +1, across all of Qloo's audiences everywhere, not this area's. "
    "Only leans "
    f"of +{LEAN:.2f} or more are shown, and none of it plays a part in choosing names."
)


class TitleAudience(BaseModel):
    """One title's audience as Qloo returned it: each band's skew, from -1 to +1."""

    entity_id: str
    age: dict[str, float] = {}
    gender: dict[str, float] = {}


def ask_audience(qloo: QlooClient, entity_id: str) -> TitleAudience | None:
    """Qloo's demographics for one title, or None when it has none, cannot answer, or
    answers in a shape this does not know (so the title is asked again next time)."""
    try:
        env = qloo.run(OPERATION, {"entity": entity_id})
    except (ReplayMiss, QlooExecError):
        return None
    if not env.has_results:
        return None
    for item in env.results:
        if item.get("entity_id") not in (None, entity_id):
            continue
        query = item.get("query")
        if not isinstance(query, dict):
            continue
        audience = TitleAudience(
            entity_id=entity_id,
            age=_skews(query.get("age"), AGE_BANDS),
            gender=_skews(query.get("gender"), GENDERS),
        )
        if audience.age or audience.gender:
            return audience
    return None


def _skews(values: object, known: dict[str, str]) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    return {
        k: float(v)
        for k, v in values.items()
        if k in known and isinstance(v, int | float) and not isinstance(v, bool)
    }


def add_audiences(result: "ListingResult", qloo: QlooClient, log: StepLog | None = None) -> bool:
    """Ask Qloo about each of a saved draft's titles not yet asked; True when none is
    missing. A title Qloo has nothing for is left out and asked again next time."""
    if result.draft is None:
        return True
    wanted = [
        i
        for i in dict.fromkeys(o.entity_id for o in result.draft.names)
        if i and i not in result.audiences
    ]
    if not wanted:
        return True
    if log is not None:
        titles = "title" if len(wanted) == 1 else f"{len(wanted)} titles"
        log.add("qloo", f"Asking Qloo who tends to like the {titles} the names come from")
    for entity_id in wanted:
        try:
            audience = ask_audience(qloo, entity_id)
        except Exception:  # noqa: BLE001 - shown only, so it never costs a checked listing
            logger.exception("audience_demographics failed for a title")
            audience = None
        if audience is not None:
            result.audiences[entity_id] = audience
    missing = [i for i in wanted if i not in result.audiences]
    if missing and log is not None:
        log.add("note", f"Qloo had no audience for {len(missing)} of them")
    return not missing


def audience_line(title: str, audience: TitleAudience | None) -> str | None:
    """The option's line: the leans Qloo returned, worded about the title's fans."""
    if audience is None:
        return None
    ages = [
        f"{label} ({audience.age[k]:+.2f})"
        for k, label in AGE_BANDS.items()
        if audience.age.get(k, 0) >= LEAN
    ]
    genders = [
        f"{label} ({audience.gender[k]:+.2f})"
        for k, label in GENDERS.items()
        if audience.gender.get(k, 0) >= LEAN
    ]
    parts = []
    if ages:
        parts.append("lean toward ages " + _and(ages))
    if genders:
        parts.append("are more often " + _and(genders))
    if not parts:
        return None
    return f"Fans of {title} {', and '.join(parts)}, across all of Qloo's audiences"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def main() -> None:
    from app.agent.results import CHECKS_VERSION
    from app.config import get_settings
    from app.runs import qloo_client
    from app.store import Store

    parser = argparse.ArgumentParser()
    parser.add_argument("--min-interval", type=float, default=10.0)
    args = parser.parse_args()
    base = get_settings()
    settings = base.model_copy(
        update={"qloo_min_interval": max(base.qloo_min_interval, args.min_interval)}
    )
    store = Store(settings.cache_db)
    qloo = qloo_client(settings)
    done = left = 0
    # Only current listings: one saved before the checks last changed is rewritten by
    # its next visitor's run, so asking about its titles would be spent for nothing.
    for result in store.saved_listings():
        if result.draft is None or result.checks_version != CHECKS_VERSION:
            continue
        before = dict(result.audiences)
        complete = add_audiences(result, qloo)
        where = f"{result.animal_id} at {result.location_id}"
        # The calls take a while; a run may have rewritten this listing meanwhile, so
        # the answers go only onto the same draft, never over a newer one.
        if result.audiences != before and not store.merge_audiences(result):
            print(f"{where}: left alone, a run rewrote it meanwhile")
            continue
        done += complete
        left += not complete
        print(f"{where}: {len(result.audiences)} titles")
    print(f"Listings complete: {done}; with a title Qloo had nothing for: {left}")


if __name__ == "__main__":
    main()
