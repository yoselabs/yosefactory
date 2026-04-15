"""Pydantic models for structured output and state management."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


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
    pr_title: str | None = None
    pr_summary: str | None = None
    ticket_summary: str | None = None
    spec_path: str | None = None
    plan_path: str | None = None
    questions: list[str] | None = None


class TicketState(BaseModel):
    """v2 state model for tracking ticket progress through the pipeline."""

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
