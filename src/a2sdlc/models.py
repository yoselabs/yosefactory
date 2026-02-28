"""Pydantic models for structured output and state management."""

from __future__ import annotations

from dataclasses import dataclass
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


class Gate(StrEnum):
    """Pipeline flags that control auto-transition at gates."""

    AUTO_PROCEED = "auto_proceed"
    AUTO_MERGE = "auto_merge"


# ── Transition table ──────────────────────────────────────────────


@dataclass(frozen=True)
class Transition:
    """Typed edge in the state machine.

    Declared on each stage class. ``next`` is the target stage (None = WAIT).
    ``gate`` is the flag that must be true to auto-transition; if the gate is
    closed the engine stops and waits for a human trigger.
    """

    next: StageName | None
    gate: Gate | None = None
    label: str = ""  # stage:X label to set on the issue
    jira_status: str = ""  # Jira status to transition to


# ── Structured output ─────────────────────────────────────────────


class StageResult(BaseModel):
    """Structured output from an agent stage."""

    status: StageStatus


class BranchState(BaseModel):
    """State file written to .a2sdlc/state.json on the agent branch."""

    stage: StageName
    status: StageStatus
    last_updated: str


@dataclass
class StageAction:
    """Deterministic action produced by the routing logic.

    Pure data — no side effects. Executed separately by ``execute_action``.
    """

    comment: str
    transition_to: str | None = None
    write_state: tuple[StageName, StageStatus] | None = None
    merge_pr: int | None = None
    post_review: tuple[int, str, str] | None = (
        None  # (pr, body, event: APPROVE|REQUEST_CHANGES)
    )


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
