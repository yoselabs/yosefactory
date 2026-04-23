"""Telemetry middleware — session + stage CMs + progress envelope.

Owns everything that dispatch used to run inside ``_run_attempted_stage``
around the handler execution: the MLflow session + stage context
managers, the ``progress_state.stage_start`` / ``stage_end`` envelope,
the ticket/stage tags, and the ``ctx.run`` run-handle assignment so
``LogMetric`` effects can reach it.

Success / error for ``stage_end`` are derived from the returned
``DispatchResult`` — no tuple plumbing required.
"""

from __future__ import annotations

import uuid

from a2sdlc.observability.progress_format import context_window_for_model
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.evaluation.telemetry import NoopTelemetry
from a2sdlc.pipeline.middleware import StageAttempt


def with_telemetry(next_: StageAttempt) -> StageAttempt:
    """Wrap ``next_`` with MLflow session + progress envelope."""

    async def run(ctx: RunContext, intent: RunIntent) -> DispatchResult:
        stage_config = ctx.stage_config
        session_id = f"{intent.event.key}:{ctx.run_id or uuid.uuid4()}"
        telemetry = ctx.telemetry or NoopTelemetry()
        with (
            telemetry.session(session_id) as opener,
            opener.stage(intent.target_stage.value) as run_handle,
        ):
            run_handle.log_tag("ticket_key", intent.event.key)
            run_handle.log_tag("target_stage", intent.target_stage.value)
            await ctx.progress_state.stage_start(
                intent.target_stage,
                session_id,
                model=stage_config.model,
                max_turns=stage_config.max_turns,
                context_window=context_window_for_model(stage_config.model) or 0,
                branch=intent.branch,
            )
            # Default to a failure-looking result so an unhandled crash
            # still produces an informative stage_end payload.
            result = DispatchResult(stage=intent.target_stage, error="unknown")
            try:
                ctx.run = run_handle
                result = await next_(ctx, intent)
                return result
            finally:
                await ctx.progress_state.stage_end(
                    intent.target_stage,
                    success=(not result.blocked and result.error is None),
                    error=result.error,
                    final=ctx.progress_state.snapshot_metrics(),
                )

    return run


__all__ = ["with_telemetry"]
