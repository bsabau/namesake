"""Run one harness workflow through the cached client and print a short summary.

    uv run python scripts/qloo_call.py find_tags '{"query": "dogs"}'
    uv run python scripts/qloo_call.py --replay where_popular '{"entity": "...", "within": "..."}'

Live results are cached and recorded under `var/`; `--replay` never calls Qloo.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.qloo.cache import Cache  # noqa: E402
from app.qloo.envelope import Envelope  # noqa: E402
from app.qloo.exec import QlooClient, harness_env  # noqa: E402


def make_client(replay: bool) -> QlooClient:
    settings = get_settings()
    return QlooClient(
        Cache(settings.cache_db),
        mode="replay" if replay else "live",
        recordings=settings.qloo_recordings,
        env=harness_env(settings),
        min_interval=settings.qloo_min_interval,
    )


def summarise(env: Envelope) -> str:
    lines = [f"status: {env.status}  results: {len(env.results)}"]
    if env.interpretation:
        lines.append("interpretation: " + json.dumps(env.interpretation)[:600])
    for w in env.warnings:
        lines.append(f"warning: {w}")
    if env.error:
        lines.append(f"error: {env.error.code} retryable={env.error.retryable}")
    for c in env.candidates:
        lines.append(f"candidate: {c.name} | {c.type} | {c.id} | {(c.description or '')[:80]}")
    for r in env.results:
        if "location" in r:
            q = r["query"]
            loc = r["location"]
            lines.append(
                f"  {loc['geohash']} {loc['latitude']:.4f},{loc['longitude']:.4f}"
                f"  aff={q.get('affinity'):.3f} pop={q.get('popularity')}"
            )
        elif "entity_id" in r:
            lines.append(
                f"  {r['name']} | {r.get('subtype') or r['type']} | {r['entity_id']}"
                f" | aff={r.get('affinity')} pop={r.get('popularity')}"
            )
        else:
            lines.append("  " + json.dumps(r)[:200])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation")
    parser.add_argument("input")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    qloo = make_client(args.replay)
    print(summarise(qloo.run(args.operation, json.loads(args.input))))
    print(f"live calls: {qloo.live_calls}")


if __name__ == "__main__":
    main()
