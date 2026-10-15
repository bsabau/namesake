"""Typed view of the result envelope that every harness workflow returns.

The harness emits two shapes. A completed run is a full envelope with a
`status`. A run rejected before it reached Qloo (bad input, missing
credentials) is a bare `{"error": ..., "operation": ..., "correlation_id": ...}`;
`Envelope.parse` folds that into the same model with status `error`.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["ok", "empty", "needs_input", "partial", "degraded", "error"]

# Statuses whose results can be shown. `partial` and `degraded` come with warnings.
USABLE: frozenset[Status] = frozenset({"ok", "partial", "degraded"})


class _Model(BaseModel):
    # The harness schema is a preview; keep fields we don't model yet.
    model_config = ConfigDict(extra="allow")


class QlooError(_Model):
    code: str
    layer: str
    retryable: bool
    recovery: str


class Candidate(_Model):
    id: str
    name: str
    type: str
    popularity: float | None = None
    description: str | None = None
    address: str | None = None


class Issue(_Model):
    input: str
    kind: str
    field: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)


class Resolution(_Model):
    issues: list[Issue] = Field(default_factory=list)


class Execution(_Model):
    transport: str | None = None
    correlation_id: str | None = None
    duration_ms: float | None = None


class Request(_Model):
    method: str
    path: str
    query: dict[str, Any] = Field(default_factory=dict)


class Provenance(_Model):
    source: str | None = None
    endpoint: str | None = None
    requests: list[Request] = Field(default_factory=list)


class Location(_Model):
    latitude: float
    longitude: float
    geohash: str


class CellScore(_Model):
    affinity: float
    popularity: float | None = None
    affinity_rank: float | None = None  # a whole rank in some responses, a fraction in others


class HeatmapCell(_Model):
    """One `where_popular` result: a map cell and how strong the entity is there."""

    location: Location
    query: CellScore


class EntityResult(_Model):
    """One `recommend` or `rank` result."""

    entity_id: str
    name: str
    type: str
    subtype: str | None = None
    affinity: float | None = None
    popularity: float | None = None


class Envelope(_Model):
    operation: str
    status: Status
    summary: str | None = None
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    interpretation: dict[str, Any] | None = None
    resolution: Resolution | None = None
    error: QlooError | None = None
    execution: Execution | None = None
    provenance: Provenance | None = None

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "Envelope":
        if "status" not in data and "error" in data:
            data = {
                "operation": data.get("operation", "unknown"),
                "status": "error",
                "error": data["error"],
                "execution": {"correlation_id": data.get("correlation_id")},
            }
        return cls.model_validate(data)

    @property
    def usable(self) -> bool:
        return self.status in USABLE

    @property
    def has_results(self) -> bool:
        # Qloo can answer `ok` with no results (seen for artists with only a
        # location), so `empty` alone is not enough to spot an empty answer.
        return self.usable and bool(self.results)

    @property
    def retryable(self) -> bool:
        return self.status == "error" and self.error is not None and self.error.retryable

    @property
    def candidates(self) -> list[Candidate]:
        """The choices Qloo offers when it could not resolve a name (`needs_input`)."""
        if self.resolution is None:
            return []
        return [c for issue in self.resolution.issues for c in issue.candidates]

    def cells(self) -> list[HeatmapCell]:
        return [HeatmapCell.model_validate(r) for r in self.results]

    def entities(self) -> list[EntityResult]:
        return [EntityResult.model_validate(r) for r in self.results]
