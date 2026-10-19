"""Check from outside that the live demo is up and its saved pages open.

Run every hour by .github/workflows/watch.yml. Checks the health route, that the start
page (its JSON and the page itself) lists every example, and that each example opens a
saved result (name options and the saved run's steps), which costs no Qloo or model
call. A failure is checked once more a minute later, so a deploy's restart does not
raise an alarm; if it fails again, the run fails and GitHub emails the author.

It never starts a run, so a dead Qloo key or model outage leaves it green: those show
in the app's log (`docker compose logs app` on the host).

Standard library only, so the workflow needs no install step.

    python3 deploy/watch.py https://namesake.bogdansabau.eu --examples 4
"""

import argparse
import html
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

# Markers of a saved result: the story skin draws these only when a run was saved, so
# results are opened in the story skin whatever the host's default.
SAVED = ('data-role="name-options"', 'data-role="run-steps"')

Fetch = Callable[[str], tuple[int, str]]


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "namesake-watch"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def problems(base: str, examples: int, get: Fetch = fetch) -> list[str]:
    """What is wrong with the live demo; empty when all is well."""
    base = base.rstrip("/")
    try:
        status, body = get(f"{base}/health")
        if status != 200 or json.loads(body or "{}").get("status") != "ok":
            return [f"/health answered {status}"]
        status, body = get(f"{base}/api/start")
        if status != 200:
            return [f"/api/start answered {status}"]
        links = json.loads(body).get("examples") or []
        found = []
        if len(links) != examples:
            found.append(f"the start page lists {len(links)} examples, not {examples}")
        status, start = get(f"{base}/")
        if status != 200:
            found.append(f"the start page answered {status}")
        for link in links:
            url, label = link.get("url", ""), link.get("label", "an example")
            if f'href="{html.escape(url)}"' not in start:
                found.append(f"{label}: not on the start page")
            status, page = get(f"{base}{url}{'&' if '?' in url else '?'}ui=story")
            if status != 200:
                found.append(f"{label}: answered {status}")
            elif not all(marker in page for marker in SAVED):
                found.append(f"{label}: no saved result")
        return found
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # OSError covers timeouts, refused connections and certificate errors.
        return [f"could not check: {type(exc).__name__}: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", help="the demo's address")
    parser.add_argument("--examples", type=int, required=True, help="how many examples")
    parser.add_argument("--retry-after", type=float, default=60)
    args = parser.parse_args()
    found = problems(args.base, args.examples)
    if found:
        print("Checking again in a minute: " + "; ".join(found))
        time.sleep(args.retry_after)
        found = problems(args.base, args.examples)
    if found:
        print("✗ " + "\n✗ ".join(found), file=sys.stderr)
        return 1
    print(f"✓ {args.base}: healthy, {args.examples} examples open their saved results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
