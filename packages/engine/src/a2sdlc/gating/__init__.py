"""Gating — pre-stage admission checks.

Owns the "can this run proceed?" boundary. Runs before a stage handler
executes; returns a string reason to block the pipeline or ``None`` to
proceed. Telemetry and ticket-level side effects (mark_blocked) are the
caller's job — these functions are pure decision logic over adapter
read-calls.

V1.0 check catalog:

- ``check_ticket_active(ctx, event)`` — skip if the ticket is no longer
  active (stale delayed events after close/resolve).
- ``check_duplicate_run_id(state_mgr, run_id)`` — skip if the current
  run_id already produced an outcome on this ticket (idempotency).
- Circuit breakers (review-cycles, cost ceiling) stay in
  ``pipeline.breakers`` — re-exported here for call-site convenience.

Architecture vision §7.3 maps these to one ``gating.check(event, ctx)``
call at the composition root. P4 keeps them as individual functions so
preflight can compose them without reshape; step 5+ collapses the call
site at the composition root.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2sdlc.gating.breakers import check_cost_ceiling, check_review_cycles

if TYPE_CHECKING:
    from a2sdlc.domain.pipeline_event import PipelineEvent
    from a2sdlc.lifecycle.state import StateManager
    from a2sdlc.domain.run_context import RunContext


def check_ticket_active(ctx: "RunContext", event: "PipelineEvent") -> str | None:
    """Return ``"ticket_not_active"`` when the ticket is closed/terminal.

    Runs before any AI call — a stale delayed event on a resolved
    ticket would otherwise kick off work for nothing.
    """
    if not ctx.work.is_ticket_active(event.key):
        ctx.logger.info(
            "dispatch.skip",
            extra={"reason": "ticket_not_active", "key": event.key},
        )
        return "ticket_not_active"
    return None


def check_duplicate_run_id(
    ctx: "RunContext",
    state_mgr: "StateManager",
    run_id: str | None,
) -> str | None:
    """Return ``"duplicate_run_id"`` if this run_id already finished.

    Idempotency guard — replays (same run_id, same ticket) early-return
    without touching adapters or the agent.
    """
    if run_id and state_mgr.check_idempotency(run_id):
        ctx.logger.info("dispatch.duplicate_run_id", extra={"run_id": run_id})
        return "duplicate_run_id"
    return None


def check(ctx: "RunContext", event: "PipelineEvent") -> str | None:
    """Run the pre-intent admission checks; return the first block reason.

    At this stage of P4, only ``check_ticket_active`` can run — the
    idempotency and circuit-breaker gates need ``state_mgr`` + the
    resolved target stage, so they stay inside ``ingress.resolve_intent``
    until a later phase can fan them out. Keeping a single ``check``
    call site here preserves the composition-root shape from
    architecture vision §7.3.
    """
    return check_ticket_active(ctx, event)


__all__ = [
    "check",
    "check_ticket_active",
    "check_duplicate_run_id",
    # Re-exported from breakers so call sites don't need two imports.
    "check_review_cycles",
    "check_cost_ceiling",
]
