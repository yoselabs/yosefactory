"""Pydantic models for structured output and state management."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ──────────────────────────────────────────────────────────


class StageName(StrEnum):
    """Pipeline stage identifiers."""

    SPEC = "spec"
    IMPLEMENT = "implement"
    REVIEW = "review"
    MERGE = "merge"


class StageStatus(StrEnum):
    """Status values emitted by agent stages."""

    COMPLETE = "complete"
    QUESTIONS = "questions"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class GateMode(StrEnum):
    """Controls how a pipeline gate is triggered."""

    AUTO = "auto"
    HUMAN = "human"


class GateConfig(BaseModel):
    """Gate configuration for the pipeline."""

    spec: GateMode = GateMode.AUTO
    merge: GateMode = GateMode.HUMAN


# ── Structured output ─────────────────────────────────────────────


class StageResult(BaseModel):
    """Structured output from an agent stage."""

    status: StageStatus
    output: str = ""


class ChildOutcome(BaseModel):
    """Placeholder for N5 backpropagation — architecture vision §2.21.

    Reserved slot so the parent ``TicketState.child_outcomes`` field has a
    concrete type before N5 lands. Fields TBD by the N5 RFC; ``extra='allow'``
    preserves round-trip of any fields a future schema adds.
    """

    model_config = ConfigDict(extra="allow")


class TicketState(BaseModel):
    """v2 state model for tracking ticket progress through the pipeline.

    Schema-versioned per ADR-0005. ``extra='allow'`` preserves unknown
    fields on round-trip (forward-compat safety).
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 2

    # v1 fields — unchanged semantics
    stage: StageName
    status: StageStatus | None = None
    base_branch: str = "main"
    branch: str
    pr_number: int | None = None
    stage_run_id: str
    review_cycles: int = 0
    accumulated_cost_usd: float = 0.0
    accumulated_tokens_in: int = 0
    accumulated_tokens_out: int = 0
    accumulated_duration_ms: int = 0
    last_updated: str

    # v2 additions — N2 (subtask execution, architecture vision §2.18)
    parent_key: str | None = None
    children: list[str] = Field(default_factory=list)
    # v2 placeholders reserved for N5 (architecture vision §2.21);
    # stay empty until the N5 RFC finalizes ``ChildOutcome`` fields.
    child_outcomes: dict[str, ChildOutcome] = Field(default_factory=dict)
    revisions: int = 0

    # Observability / reproducibility (ADR-0005)
    engine_version: str = ""
    workflow_name: str = "default"

    # Rate-limit self-heal slot (architecture vision §2.23);
    # scheduled sweep re-dispatches after this ISO timestamp clears.
    rate_limited_until: str | None = None


def extract_result(output: str) -> StageResult | None:
    """Extract the ``a2sdlc`` JSON block from agent output.

    Returns ``None`` if no valid block is found.
    """
    marker = "```a2sdlc"
    start = output.rfind(marker)
    if start == -1:
        return None
    start += len(marker)
    end = output.find("```", start)
    if end == -1:
        return None
    raw = output[start:end].strip()
    try:
        return StageResult.model_validate_json(raw)
    except Exception:  # noqa: BLE001
        return None


def strip_status_block(output: str) -> str:
    """Remove the ``a2sdlc`` fenced code block from output text."""
    marker = "```a2sdlc"
    start = output.rfind(marker)
    if start == -1:
        return output
    end = output.find("```", start + len(marker))
    if end == -1:
        return output
    # Include the closing ``` in the removal
    end += len("```")
    return (output[:start] + output[end:]).strip()
