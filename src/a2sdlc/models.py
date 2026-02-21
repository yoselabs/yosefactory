"""Pydantic models for structured output and state management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel


class StageStatus(StrEnum):
    """Status values emitted by agent stages."""

    COMPLETE = "complete"
    QUESTIONS = "questions"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class StageResult(BaseModel):
    """Structured output from an agent stage."""

    status: StageStatus


class BranchState(BaseModel):
    """State file written to .a2sdlc/state.json on the agent branch."""

    stage: str
    status: str
    last_updated: str


@dataclass
class StageAction:
    """Deterministic action produced by the routing logic.

    Pure data — no side effects. Executed separately by ``execute_action``.
    """

    comment: str
    transition_to: str | None = None
    write_state: tuple[str, str] | None = None  # (stage, status)
    merge_pr: int | None = None


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
