"""MERGE stage — deterministic squash merge + cleanup. No AI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2sdlc.config import StageConfig
from a2sdlc.domain.block_reason import BlockReason
from a2sdlc.domain.models import GateMode, StageName, StageStatus
from a2sdlc.domain.stage_outcome import StageOutcome

if TYPE_CHECKING:
    from a2sdlc.pipeline.dispatch import DispatchContext


class MergeStage:
    """MERGE stage handler — P2 step 8.

    Absorbs the body previously held in ``pipeline.merge_flow.execute_merge``.
    No AI: gated on human approval when ``gates.merge == HUMAN``, then
    runtime-state strip → PR title promotion → squash merge → mark done.

    ``valid_statuses`` is empty by design — MERGE is deterministic and
    never emits a ``StageStatus``. ``StageOutcome.merged`` is the
    success discriminator (True on successful merge, False/None on
    blocked paths).
    """

    name = StageName.MERGE
    uses_ai = False
    valid_statuses = frozenset[StageStatus]()
    config = StageConfig(name="merge", max_turns=0, timeout_minutes=5)

    def preconditions(self, ctx: "DispatchContext") -> BlockReason | None:
        return None

    def effects(self, ctx: "DispatchContext", outcome: StageOutcome) -> list[object]:
        return []

    async def execute(self, ctx: "DispatchContext") -> StageOutcome:
        pre = _require(ctx.pre, "pre")
        comment = _require(ctx.comment, "comment")
        pr_lifecycle = _require(ctx.pr_lifecycle, "pr_lifecycle")
        pr_number = ctx.pr_number

        # 1. No PR → block. MERGE cannot run without a PR to merge.
        if pr_number is None:
            reason = f"No PR found for branch {pre.branch}"
            comment.finalize(f"\U0001f6a8 {reason}")
            ctx.work.mark_blocked(pre.event.key, reason)
            return StageOutcome(blocked=True, error=reason, merged=False)

        # 2. Human gate → block, pipeline pauses for human approval.
        if pre.gates.merge == GateMode.HUMAN and not pr_lifecycle.check_human_approval(
            pr_number
        ):
            comment.finalize("⏳ Waiting for human approval before merge.")
            return StageOutcome(
                blocked=True, error="waiting_for_approval", merged=False
            )

        # 3. Sync base, strip runtime state, promote title, merge.
        ctx.git.sync_with_base(pre.base)
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

        return StageOutcome(merged=True)


def _require(value, name):  # type: ignore[no-untyped-def]
    if value is None:
        msg = f"MergeStage.execute requires ctx.{name} to be populated by dispatch"
        raise RuntimeError(msg)
    return value
