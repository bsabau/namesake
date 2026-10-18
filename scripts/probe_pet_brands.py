"""Probe: do pet-supply brands make better venue signals than pet-themed titles?

Fans of a pet-supply brand are more likely to own a pet than fans of a cartoon
about one, so their places might suit an adoption flyer better. This looks up
a few brands, asks for places near Park Slope that their fans favour, and
compares those with the saved dog profile's venues and the baseline's.

    uv run python scripts/probe_pet_brands.py          # replay; spends no quota
    uv run python scripts/probe_pet_brands.py --live   # about 5 live calls, spaced

IDs are picked at run time from Qloo's answers, never written here. The
answers are written up in `docs/qloo-findings.md`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.locations import load_locations  # noqa: E402
from app.profile import (  # noqa: E402
    HEATMAP_LIMIT,
    VENUE_LIMIT,
    baseline_titles,
    baseline_venue_ids,
)
from app.qloo.exec import QlooExecError, ReplayMiss  # noqa: E402
from app.store import Store  # noqa: E402
from scripts.qloo_call import make_client  # noqa: E402

BRANDS = ["Chewy", "BarkBox", "Purina"]
PET_WORDS = ("pet", "dog", "cat", "animal")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    qloo = make_client(replay=not args.live)
    location = next(x for x in load_locations(settings.locations_file) if x.id == "park-slope")
    profile = Store(settings.cache_db).get_profile(location.id, "dog")

    def call(operation, input_):
        try:
            return qloo.run(operation, input_)
        except (ReplayMiss, QlooExecError) as exc:
            print(f"  {operation}: {exc}")
            return None

    brands = []
    for name in BRANDS:
        env = call("describe", {"entity": name, "type": "brand"})
        if env is None:
            continue
        options = (
            [(c.id, c.name, c.description) for c in env.candidates]
            if env.status == "needs_input"
            else [
                (r["entity_id"], r["name"], (r.get("properties") or {}).get("short_description"))
                for r in env.results
            ]
        )
        pet = [o for o in options if any(w in (o[2] or "").lower() for w in PET_WORDS)]
        print(f"{name}: {env.status}, {len(options)} entries, {len(pet)} about pets")
        for _, found, description in pet[:1]:
            print(f"  picked {found}: {(description or '')[:120]}")
        if pet:
            brands.append(pet[0])

    if not brands:
        print("No pet brand found; stopping.")
        return

    env = call(
        "recommend",
        {
            "target_type": "place",
            "signals": [b[0] for b in brands],
            "filter_location": location.query,
            "limit": VENUE_LIMIT,
        },
    )
    if env is None or not env.has_results:
        print(f"Brand venues: {env.status if env else 'unavailable'}")
        return
    bases = baseline_titles(profile)
    base_ids = baseline_venue_ids(qloo, location, bases)[1] if bases else None
    titles = {v.entity_id: v for v in profile.venues}
    print(f"\nPlaces near {location.label} for fans of {', '.join(b[1] for b in brands)}:")
    shared_titles = shared_base = 0
    for rank, r in enumerate(env.results, 1):
        in_titles = titles.get(r["entity_id"])
        in_base = base_ids is not None and r["entity_id"] in base_ids
        shared_titles += in_titles is not None
        shared_base += in_base
        marks = []
        if in_titles:
            marks.append(f"films' #{in_titles.rank}")
        if in_base:
            marks.append(f"baseline #{base_ids.index(r['entity_id']) + 1}")
        description = ((r.get("properties") or {}).get("short_description") or "")[:70]
        print(f"  {rank:2}. {r['name']} [{', '.join(marks) or 'new'}] {description}")
    print(
        f"\n{len(env.results)} places: {shared_titles} also on the pet films' list, "
        f"{shared_base} also on the baseline's ({', '.join(e.name for e in bases)})."
    )

    cells = call("where_popular", {"entity": brands[0][0], "within": location.query,
                                   "limit": HEATMAP_LIMIT})  # fmt: skip
    if cells is not None:
        print(
            f"\nHeatmap for {brands[0][1]} within {location.label}: {cells.status}, "
            f"{len(cells.results)} cells (the pet films' map has {len(profile.cells)})"
        )


if __name__ == "__main__":
    main()
