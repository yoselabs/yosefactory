"""MERGE stage — deterministic squash merge + cleanup. No AI."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageAction, StageName, StageStatus, Transition


class MergeStage:
    name = StageName.MERGE
    uses_ai = False
    valid_statuses = frozenset[StageStatus]()
    transitions: dict[StageStatus, Transition] = {}  # terminal stage
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
