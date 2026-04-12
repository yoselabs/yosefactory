"""REVIEW stage — independent PR review."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName, StageStatus


class ReviewStage:
    name = StageName.REVIEW
    uses_ai = True
    valid_statuses = frozenset({StageStatus.APPROVED, StageStatus.CHANGES_REQUESTED})
    transitions: dict[StageStatus, StageName | None] = {
        StageStatus.APPROVED: StageName.MERGE,
        StageStatus.CHANGES_REQUESTED: StageName.IMPLEMENT,
    }
    config = StageConfig(
        name="review",
        max_turns=150,
        timeout_minutes=20,
        allowed_tools=["Bash", "Read", "Glob", "Grep", "WebFetch", "WebSearch"],
    )
