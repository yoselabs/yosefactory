"""Pydantic models for structured output and state management."""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from a2sdlc.domain.stage_outcome import InlineComment


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


def extract_inline_comments(
    output: str, logger: logging.Logger | None = None
) -> list[InlineComment]:
    """Extract the optional ``inline_comments`` list from the a2sdlc block.

    REVIEW agents may include ``inline_comments: [...]`` alongside
    ``status`` inside the fenced block. Each entry must match the
    ``InlineComment`` shape (file, line_start, line_end, body, side).

    Tolerant parsing per P2 step 7 spec: missing field → empty list,
    malformed entries dropped with a warning (not fatal). Non-REVIEW
    stages never produce this field, so callers for IMPLEMENT / SPEC
    get an empty list without checking stage.
    """
    from a2sdlc.domain.stage_outcome import InlineComment  # avoid cycle

    marker = "```a2sdlc"
    start = output.rfind(marker)
    if start == -1:
        return []
    start += len(marker)
    end = output.find("```", start)
    if end == -1:
        return []
    raw = output[start:end].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    entries = payload.get("inline_comments") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []

    comments: list[InlineComment] = []
    for idx, entry in enumerate(entries):
        try:
            comments.append(InlineComment.model_validate(entry))
        except Exception as exc:  # noqa: BLE001
            if logger is not None:
                logger.warning(
                    "inline_comment.malformed",
                    extra={"index": idx, "error": str(exc)},
                )
    return comments


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
