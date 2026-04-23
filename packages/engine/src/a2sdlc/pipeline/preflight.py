"""Preflight phase of dispatch — event parsing through circuit breakers.

Runs synchronously before any AI call or network write; its job is to
resolve *what should happen* (which stage, with which inputs) and
*whether it should happen at all* (skip / closed / inactive / duplicate
/ tripped breaker). Returns either a `PreflightOutcome` with everything
the stage execution needs, or a terminal `DispatchResult` that the
caller returns directly.

Extracted from `dispatch.py` to keep the composition root under the
500-line cap and make the routing logic testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from a2sdlc.config import load_stage_config
from a2sdlc.domain.directives import parse_directives
from a2sdlc.domain.exceptions import BlockedError, SkipEvent
from a2sdlc.domain.models import GateConfig, StageName
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.lifecycle.state import StateManager
from a2sdlc.lifecycle.state_storage import GitFileStateStorage
from a2sdlc.pipeline.gating import (
    check_cost_ceiling,
    check_duplicate_run_id,
    check_review_cycles,
    check_ticket_active,
)
from a2sdlc.pipeline.ingress import resolve_routing as _resolve_routing

if TYPE_CHECKING:
    from a2sdlc.domain.models import TicketState
    from a2sdlc.domain.pipeline_event import PipelineEvent
    from a2sdlc.pipeline.dispatch import DispatchContext


@dataclass
class PreflightOutcome:
    """What preflight hands to stage execution. All fields resolved."""

    event: "PipelineEvent"
    target_stage: StageName
    clean_body: str
    user_prompt_override: str | None
    gates: GateConfig
    self_answer: bool
    state_mgr: StateManager
    state: "TicketState | None"
    base: str
    branch: str


PreflightResult = Union[PreflightOutcome, DispatchResult]


def run_preflight(ctx: "DispatchContext") -> PreflightResult:
    """Resolve the stage to run + all inputs, or short-circuit with a
    terminal DispatchResult.

    Short-circuit cases (caller returns the DispatchResult directly):
    - SkipEvent from parse_event
    - Ticket closed (mark_done side-effect here; no AI call)
    - Ticket not active
    - Git setup blocked
    - Duplicate run_id (idempotency)
    - Circuit breaker tripped (review-cycles or cost ceiling)
    """
    # 1. Parse event
    try:
        event = ctx.work.parse_event()
    except SkipEvent as e:
        ctx.logger.info("dispatch.skip", extra={"reason": e.reason})
        return DispatchResult(stage=StageName.SPEC, error=e.reason)

    # 1.5 Ticket-closed: stamp done, strip transient labels, no AI call.
    # Handled before is_ticket_active because the close IS the signal.
    if event.is_closed:
        ctx.logger.info("dispatch.ticket_closed", extra={"key": event.key})
        ctx.work.mark_done(event.key)
        return DispatchResult(stage=StageName.MERGE, error="ticket_closed")

    # 1.6 Skip stages on terminal tickets (stale delayed events, etc.).
    if reason := check_ticket_active(ctx, event):
        return DispatchResult(stage=StageName.SPEC, error=reason)

    # 2. Ticket body + directives
    ticket_body = ctx.work.get_ticket(event.key)
    directives, clean_body = parse_directives(ticket_body)

    # ── Route: feedback / proceed / label ──────────────────────
    user_prompt_override, target_stage, routing_result = _resolve_routing(
        ctx, event, clean_body
    )
    if routing_result is not None:
        return routing_result

    # ── Shared setup continues ────────────────────────────────
    ctx.logger.info(
        "dispatch.start",
        extra={"key": event.key, "stage": target_stage.value},
    )

    gates = ctx.config.gate_config()
    if directives.gate_merge is not None:
        gates = GateConfig(merge=directives.gate_merge, spec=gates.spec)
    if directives.gate_spec is not None:
        gates = GateConfig(merge=gates.merge, spec=directives.gate_spec)

    self_answer = ctx.config.self_answer

    # 3. Branch setup — state.json lives on the ticket branch so we must
    # checkout before reading it.
    state_mgr = StateManager(GitFileStateStorage(ctx.git), event.key)
    base = directives.base or ctx.config.default_base
    branch = ctx.work.format_branch(event.key)
    try:
        ctx.git.setup_branch(branch, base)
        ctx.logger.info("dispatch.branch_setup", extra={"branch": branch, "base": base})
    except BlockedError as e:
        ctx.logger.error("dispatch.git_blocked", extra={"reason": e.reason})
        ctx.work.mark_blocked(event.key, e.reason)
        return DispatchResult(stage=target_stage, blocked=True, error=e.reason)

    # 4. Read state + idempotency check (branch is now checked out).
    state = state_mgr.read_state()

    if reason := check_duplicate_run_id(ctx, state_mgr, ctx.run_id):
        return DispatchResult(stage=target_stage, error=reason)

    # 5. Circuit breakers — review-cycle loop + per-ticket cost ceiling.
    stage_cfg = load_stage_config(target_stage.value, ctx.config)
    for reason in (
        check_review_cycles(target_stage, state, stage_cfg),
        check_cost_ceiling(state, ctx.config),
    ):
        if reason is not None:
            ctx.logger.error("dispatch.circuit_breaker", extra={"reason": reason})
            ctx.work.mark_blocked(event.key, reason)
            return DispatchResult(stage=target_stage, blocked=True, error=reason)

    return PreflightOutcome(
        event=event,
        target_stage=target_stage,
        clean_body=clean_body,
        user_prompt_override=user_prompt_override,
        gates=gates,
        self_answer=self_answer,
        state_mgr=state_mgr,
        state=state,
        base=base,
        branch=branch,
    )


__all__ = ["PreflightOutcome", "PreflightResult", "run_preflight"]
