"""Merge stage — deterministic, no AI.

Gated on human approval if `gate.merge == HUMAN`. Owns the pre-merge
runtime-state strip, engine-side PR title update (source of truth is the
tracker ticket title), and the merge itself. Called from `dispatch.py`
when `target_stage == MERGE`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2sdlc.domain.models import GateMode, StageName
from a2sdlc.domain.run_result import DispatchResult

if TYPE_CHECKING:
    from a2sdlc.lifecycle.comment import CommentManager
    from a2sdlc.lifecycle.pr import PRLifecycle
    from a2sdlc.pipeline.dispatch import DispatchContext
    from a2sdlc.pipeline.preflight import PreflightOutcome


def execute_merge(
    ctx: "DispatchContext",
    pre: "PreflightOutcome",
    pr_lifecycle: "PRLifecycle",
    comment: "CommentManager",
    pr_number: int | None,
) -> tuple[DispatchResult, bool, str | None]:
    """Run the MERGE stage.

    Returns `(result, success, error)`. The bool + error are threaded
    back to the caller's `progress_state.stage_end` emission — callers
    shouldn't need to reconstruct them from the DispatchResult.
    """
    if pr_number is None:
        reason = f"No PR found for branch {pre.branch}"
        comment.finalize(f"\U0001f6a8 {reason}")
        ctx.work.mark_blocked(pre.event.key, reason)
        return (
            DispatchResult(stage=StageName.MERGE, blocked=True, error=reason),
            False,
            reason,
        )

    if pre.gates.merge == GateMode.HUMAN and not pr_lifecycle.check_human_approval(
        pr_number
    ):
        comment.finalize("⏳ Waiting for human approval before merge.")
        return (
            DispatchResult(
                stage=StageName.MERGE,
                blocked=True,
                error="waiting_for_approval",
            ),
            False,
            "waiting_for_approval",
        )

    ctx.git.sync_with_base(pre.base)
    # Strip state, promote title, merge. Engine owns all PR ops.
    try:
        ctx.git.strip_runtime_state()
    except Exception:  # noqa: BLE001
        ctx.logger.warning("dispatch.state_strip_failed", exc_info=True)
    if tt := ctx.work.get_ticket_title(pre.event.key):
        pr_lifecycle.update_title(pr_number, tt)
    pr_lifecycle.merge(pr_number)
    comment.finalize(f"✅ Merged #{pr_number}")
    ctx.work.mark_done(pre.event.key)
    ctx.logger.info("dispatch.merged", extra={"pr": pr_number})
    return DispatchResult(stage=StageName.MERGE), True, None


__all__ = ["execute_merge"]
