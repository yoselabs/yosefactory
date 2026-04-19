"""Wire-format Pydantic models for engine → dispatcher domain events.

Known event kinds are decoded into typed models. Unknown kinds are accepted
as a forward-compat fallback so the engine can emit new kinds ahead of
dispatcher awareness without breaking ingestion.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class RunStarted(BaseModel):
    kind: Literal["run_started"] = "run_started"
    run_id: str
    mlflow_url: str | None = None


class StageStarted(BaseModel):
    kind: Literal["stage_started"] = "stage_started"
    stage: str


class StageCompleted(BaseModel):
    kind: Literal["stage_completed"] = "stage_completed"
    stage: str
    ok: bool
    summary: str | None = None


class PROpened(BaseModel):
    kind: Literal["pr_opened"] = "pr_opened"
    url: str
    base: str
    head: str


class PRUpdated(BaseModel):
    kind: Literal["pr_updated"] = "pr_updated"
    url: str
    update_kind: Literal["ci-green", "changes-requested", "approved"]


class RunCompleted(BaseModel):
    kind: Literal["run_completed"] = "run_completed"
    pr_url: str | None = None
    outcome: Literal["awaiting_merge", "merged", "failed"]


class RunFailed(BaseModel):
    kind: Literal["run_failed"] = "run_failed"
    error: str
    mlflow_url: str | None = None


class UnknownEvent(BaseModel):
    """Forward-compat — any kind we don't explicitly model."""

    model_config = {"extra": "allow"}
    kind: str


KnownEvent = Annotated[
    RunStarted
    | StageStarted
    | StageCompleted
    | PROpened
    | PRUpdated
    | RunCompleted
    | RunFailed,
    Field(discriminator="kind"),
]

_KNOWN_KINDS = {
    "run_started",
    "stage_started",
    "stage_completed",
    "pr_opened",
    "pr_updated",
    "run_completed",
    "run_failed",
}


def _validate(data: dict):
    k = data.get("kind")
    if k is None:
        raise ValidationError.from_exception_data(
            "DomainEvent",
            [{"type": "missing", "loc": ("kind",), "input": data}],
        )
    if k in _KNOWN_KINDS:
        return TypeAdapter(KnownEvent).validate_python(data)
    return UnknownEvent.model_validate(data)


class _Adapter:
    """Callable wrapper exposing validate_python like a TypeAdapter."""

    @staticmethod
    def validate_python(data: dict):
        return _validate(data)


DomainEventAdapter = _Adapter()
