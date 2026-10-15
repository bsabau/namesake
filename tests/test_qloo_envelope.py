import json
from pathlib import Path

import pytest

from app.qloo.envelope import Envelope

SYNTHETIC = Path(__file__).parent / "fixtures" / "qloo" / "synthetic"


def load(name: str) -> dict:
    return json.loads((SYNTHETIC / f"{name}.json").read_text(encoding="utf-8"))


def test_heatmap_cells():
    env = Envelope.parse(load("where_popular__ok"))
    assert env.status == "ok" and env.usable and env.has_results
    cells = env.cells()
    assert [c.query.affinity_rank for c in cells] == [1, 2, 0.95]
    assert len(cells[0].location.geohash) == 6
    assert env.provenance.requests[0].query["filter.type"] == "urn:heatmap"


def test_recommend_entities():
    env = Envelope.parse(load("recommend__ok"))
    names = [e.name for e in env.entities()]
    assert names == ["Example Dog Show", "Example Cat Show"]
    assert env.interpretation["signal_location"] == "Example Neighbourhood"


def test_needs_input_exposes_candidates_and_is_not_usable():
    env = Envelope.parse(load("where_popular__needs_input"))
    assert env.status == "needs_input"
    assert not env.usable and not env.has_results
    assert [c.type for c in env.candidates] == ["urn:entity:tv_show", "urn:entity:book"]


def test_ok_with_no_results_has_no_results():
    env = Envelope.parse(load("recommend__empty"))
    assert env.status == "ok" and not env.has_results


def test_partial_keeps_warnings():
    env = Envelope.parse(load("recommend__partial"))
    assert env.usable and env.warnings == ["One signal could not be applied."]


@pytest.mark.parametrize("status", ["empty", "degraded"])
def test_other_statuses_parse(status):
    env = Envelope.parse({"operation": "recommend", "status": status, "results": []})
    assert env.status == status
    assert env.usable is (status == "degraded")


@pytest.mark.parametrize(
    ("name", "retryable"),
    [("error__retryable", True), ("error__not_retryable", False), ("error__tool_input", False)],
)
def test_bare_error_becomes_an_error_envelope(name, retryable):
    env = Envelope.parse(load(name))
    assert env.status == "error" and not env.usable
    assert env.retryable is retryable
    assert env.execution.correlation_id.startswith("exec-synthetic-")


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError):
        Envelope.parse({"operation": "recommend", "status": "maybe"})
