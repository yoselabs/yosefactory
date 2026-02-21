"""MERGE stage — deterministic squash merge + cleanup. No AI."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageAction, StageStatus


class MergeStage:
    name = "merge"
    uses_ai = False
    valid_statuses = frozenset[StageStatus]()
    config = StageConfig(name="merge", max_turns=0, timeout_minutes=5)

    def resolve(
        self,
        status: StageStatus,
        comment_body: str,
        cost_footer: str,
        **kwargs: object,
    ) -> StageAction:
        return StageAction(
            comment=f"⚠️ Merge stage does not use resolve()\n\n{cost_footer}",
        )
