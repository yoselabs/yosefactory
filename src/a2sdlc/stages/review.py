"""REVIEW stage — independent PR review."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import Gate, StageName, StageStatus, Transition


class ReviewStage:
    name = StageName.REVIEW
    uses_ai = True
    valid_statuses = frozenset({StageStatus.APPROVED, StageStatus.CHANGES_REQUESTED})
    transitions: dict[StageStatus, Transition] = {
        StageStatus.APPROVED: Transition(
            next=StageName.MERGE,
            gate=Gate.AUTO_MERGE,
        ),
        StageStatus.CHANGES_REQUESTED: Transition(
            next=StageName.IMPLEMENT,
        ),
    }
    config = StageConfig(
        name="review",
        max_turns=25,
        timeout_minutes=20,
        allowed_tools=["Bash", "Read", "Glob", "Grep", "WebFetch", "WebSearch"],
    )
