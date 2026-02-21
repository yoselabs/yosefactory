"""REVIEW stage — independent PR review."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageAction, StageStatus


class ReviewStage:
    name = "review"
    uses_ai = True
    valid_statuses = frozenset({StageStatus.APPROVED, StageStatus.CHANGES_REQUESTED})
    config = StageConfig(
        name="review",
        max_turns=25,
        timeout_minutes=20,
        allowed_tools=["Bash", "Read", "Glob", "Grep", "WebFetch", "WebSearch"],
    )

    def resolve(
        self,
        status: StageStatus,
        comment_body: str,
        cost_footer: str,
        **kwargs: object,
    ) -> StageAction:
        auto_merge = bool(kwargs.get("auto_merge", False))
        raw_pr = kwargs.get("pr_number")
        merge_pr: int | None = None
        if auto_merge and raw_pr is not None:
            merge_pr = int(str(raw_pr))
        if status == StageStatus.APPROVED:
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                merge_pr=merge_pr,
            )
        if status == StageStatus.CHANGES_REQUESTED:
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                transition_to="needs-fix",
            )
        return StageAction(
            comment=f"⚠️ Unexpected status {status} for review\n\n{cost_footer}",
        )
