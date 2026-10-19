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
                {
                    "examples": [
                        {"label": f"Ex {i}", "url": f"/r?i={i}&x=1"} for i in range(examples)
                    ]
                }
            ),
        ),
        "/": (200, "".join(f'<a href="/r?i={i}&amp;x=1">' for i in range(examples))),
        **{f"/r?i={i}&x=1&ui=story": (200, SAVED_PAGE) for i in range(examples)},
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
    unsaved = site(**{"/r?i=1&x=1&ui=story": (200, "<p>Start</p>")})
    assert watch.problems("https://demo.invalid", 2, unsaved) == ["Ex 1: no saved result"]
    broken = site(**{"/r?i=0&x=1&ui=story": (502, "")})
    assert watch.problems("https://demo.invalid", 2, broken) == ["Ex 0: answered 502"]


def test_a_broken_start_page_fails_even_when_its_json_is_fine():
    # Codex: the page itself was never opened, so a broken template passed.
    found = watch.problems("https://demo.invalid", 2, site(**{"/": (500, "")}))
    assert found[0] == "the start page answered 500"
    assert "Ex 0: not on the start page" in found


def test_a_down_site_stops_at_the_first_failure():
    assert watch.problems("https://demo.invalid", 2, site(**{"/health": (502, "")})) == [
        "/health answered 502"
    ]

    def refused(url):
        raise ConnectionRefusedError("refused")

    (problem,) = watch.problems("https://demo.invalid", 2, refused)
    assert problem.startswith("could not check: ConnectionRefusedError")
    # muse: a wrongly shaped example list is reported, not a traceback.
    odd = site(**{"/api/start": (200, '{"examples": ["x", "y"]}')})
    (problem,) = watch.problems("https://demo.invalid", 2, odd)
    assert problem.startswith("could not check: AttributeError")


def test_the_workflow_expects_every_example():
    workflow = (ROOT / ".github" / "workflows" / "watch.yml").read_text()
    assert int(re.search(r"--examples (\d+)", workflow).group(1)) == len(EXAMPLES)


def test_main_checks_again_once_and_fails_only_if_the_problem_holds(monkeypatch, capsys):
    # Flash: the retry and the exit code were untested.
    answers = [["/health answered 502"], []]
    monkeypatch.setattr(watch, "problems", lambda base, examples: answers.pop(0))
    argv = ["watch.py", "https://demo.invalid", "--examples", "2", "--retry-after", "0"]
    monkeypatch.setattr("sys.argv", argv)
    assert watch.main() == 0 and answers == []
    assert "Checking again" in capsys.readouterr().out

    answers = [["/health answered 502"], ["/health answered 502"]]
    assert watch.main() == 1 and answers == []
    assert "✗ /health answered 502" in capsys.readouterr().err
