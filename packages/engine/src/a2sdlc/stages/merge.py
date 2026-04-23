"""MERGE stage — deterministic squash merge + cleanup. No AI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2sdlc.config import StageConfig
from a2sdlc.domain.block_reason import BlockReason
from a2sdlc.domain.effects import (
    AwaitHumanDecision,
    CommentFinalize,
    Effect,
    MarkBlocked,
    MarkDone,
    MergePR,
    StripRuntimeState,
    SyncBase,
    UpdatePRTitle,
)
from a2sdlc.domain.models import GateMode, StageName, StageStatus
from a2sdlc.domain.stage_outcome import StageOutcome

if TYPE_CHECKING:
    from a2sdlc.pipeline.dispatch import DispatchContext


class MergeStage:
    """MERGE stage handler — P3 step 7 (effects migration).

    ``execute()`` reduces to the gate checks (no PR → block, HUMAN gate
    without approval → block, approved → success). The full merge
    sequence (sync → strip runtime state → update PR title → squash
    merge → mark done → finalize comment) flows through the effect list.
    """

    name = StageName.MERGE
    uses_ai = False
    valid_statuses = frozenset[StageStatus]()
    config = StageConfig(name="merge", max_turns=0, timeout_minutes=5)

    def preconditions(self, ctx: "DispatchContext") -> BlockReason | None:
        return None

    def effects(self, ctx: "DispatchContext", outcome: StageOutcome) -> list[Effect]:
        return list(outcome.prepared_effects)

    async def execute(self, ctx: "DispatchContext") -> StageOutcome:
        pre = _require(ctx.pre, "pre")
        pr_lifecycle = _require(ctx.pr_lifecycle, "pr_lifecycle")
        pr_number = ctx.pr_number

        # 1. No PR → platform-blocked (ticket marked, pipeline paused).
        if pr_number is None:
            reason = f"No PR found for branch {pre.branch}"
            effects: list[Effect] = [
                CommentFinalize(body=f"\U0001f6a8 {reason}"),
                MarkBlocked(reason=reason),
            ]
            return StageOutcome(merged=False, prepared_effects=effects)

        # 2. Human gate → pipeline pause only (no platform flag — ticket
        # stays in stage:merge awaiting an Approve click). AwaitHumanDecision
        # is the first-class signal dispatch reads for pause semantics.
        if pre.gates.merge == GateMode.HUMAN and not pr_lifecycle.check_human_approval(
            pr_number
        ):
            effects = [
                CommentFinalize(body="⏳ Waiting for human approval before merge."),
                AwaitHumanDecision(kind="approval", reason="waiting_for_approval"),
            ]
            return StageOutcome(merged=False, prepared_effects=effects)

        # 3. Success — build the full merge sequence as effects. Ordering
        # matters: sync + strip before merge; merge before mark_done.
        success_effects: list[Effect] = []
        success_effects.append(SyncBase(base=pre.base))
        success_effects.append(StripRuntimeState())
        if tt := ctx.work.get_ticket_title(pre.event.key):
            success_effects.append(UpdatePRTitle(pr_number=pr_number, title=tt))
        success_effects.append(MergePR(pr_number=pr_number))
        success_effects.append(CommentFinalize(body=f"✅ Merged #{pr_number}"))
        success_effects.append(MarkDone())
        ctx.logger.info("dispatch.merged", extra={"pr": pr_number})

        return StageOutcome(merged=True, prepared_effects=success_effects)


def _require(value, name):  # type: ignore[no-untyped-def]
    if value is None:
        msg = f"MergeStage.execute requires ctx.{name} to be populated by dispatch"
        raise RuntimeError(msg)
    return value
