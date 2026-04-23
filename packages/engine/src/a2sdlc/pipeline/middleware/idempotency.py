"""Idempotency middleware — short-circuits duplicate ``run_id`` replays.

Reads per-ticket state via ``intent.state_mgr``; delegates the actual
decision to ``gating.check_duplicate_run_id`` so the "what counts as
a duplicate?" rule stays in one place.

Sits outside ``with_telemetry`` in the composition — a dupe run must
not open a telemetry session (no MLflow run for replays).
"""

from __future__ import annotations

from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.pipeline import gating
from a2sdlc.pipeline.middleware import StageAttempt


def with_idempotency(next_: StageAttempt) -> StageAttempt:
    """Wrap ``next_`` with a duplicate-run_id short-circuit."""

    async def run(ctx: RunContext, intent: RunIntent) -> DispatchResult:
        reason = gating.check_duplicate_run_id(ctx, intent.state_mgr, ctx.run_id)
        if reason is not None:
            return DispatchResult(stage=intent.target_stage, error=reason)
        return await next_(ctx, intent)

    return run


__all__ = ["with_idempotency"]
