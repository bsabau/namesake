"""deploy/watch.py: the hourly check of the live demo, against a fake site.

No network: every page comes from a dictionary.
"""

import importlib.util
import json
import re
from pathlib import Path

from app.views.build import EXAMPLES

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("watch", ROOT / "deploy" / "watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

SAVED_PAGE = '<ul data-role="name-options"></ul><details data-role="run-steps"></details>'


def site(examples=2, **override):
    pages = {
        "/health": (200, '{"status": "ok"}'),
        "/api/start": (
            200,
            json.dumps(
                {"examples": [{"label": f"Ex {i}", "url": f"/r?i={i}"} for i in range(examples)]}
            ),
        ),
        **{f"/r?i={i}": (200, SAVED_PAGE) for i in range(examples)},
        **override,
    }

    def get(url):
        return pages[url.removeprefix("https://demo.invalid")]

    return get


def test_a_healthy_site_has_no_problems():
    assert watch.problems("https://demo.invalid/", 2, site()) == []


def test_a_missing_example_or_an_unsaved_result_is_named():
    assert watch.problems("https://demo.invalid", 3, site()) == [
        "the start page lists 2 examples, not 3"
    ]
    found = watch.problems("https://demo.invalid", 2, site(**{"/r?i=1": (200, "<p>Start</p>")}))
    assert found == ["Ex 1: no saved result"]
    found = watch.problems("https://demo.invalid", 2, site(**{"/r?i=0": (502, "")}))
    assert found == ["Ex 0: answered 502"]


def test_a_down_site_stops_at_the_first_failure():
    assert watch.problems("https://demo.invalid", 2, site(**{"/health": (502, "")})) == [
        "/health answered 502"
    ]

    def refused(url):
        raise ConnectionRefusedError("refused")

    (problem,) = watch.problems("https://demo.invalid", 2, refused)
    assert problem.startswith("could not check: ConnectionRefusedError")


def test_the_workflow_expects_every_example():
    workflow = (ROOT / ".github" / "workflows" / "watch.yml").read_text()
    assert int(re.search(r"--examples (\d+)", workflow).group(1)) == len(EXAMPLES)
