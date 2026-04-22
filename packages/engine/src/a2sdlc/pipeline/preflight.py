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
from datetime import datetime
from typing import TYPE_CHECKING, Union

from a2sdlc.config import load_stage_config
from a2sdlc.domain.directives import parse_directives
from a2sdlc.domain.exceptions import BlockedError, SkipEvent
from a2sdlc.domain.models import GateConfig, StageName
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.lifecycle.state import StateManager
from a2sdlc.lifecycle.state_storage import GitFileStateStorage
from a2sdlc.pipeline.breakers import check_cost_ceiling, check_review_cycles
from a2sdlc.pipeline.context import assemble_context, pick_handover
from a2sdlc.pipeline.feedback_routing import resolve_target_stage

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
    if not ctx.work.is_ticket_active(event.key):
        ctx.logger.info(
            "dispatch.skip",
            extra={"reason": "ticket_not_active", "key": event.key},
        )
        return DispatchResult(stage=StageName.SPEC, error="ticket_not_active")

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

    if ctx.run_id and state_mgr.check_idempotency(ctx.run_id):
        ctx.logger.info("dispatch.duplicate_run_id", extra={"run_id": ctx.run_id})
        return DispatchResult(stage=target_stage, error="duplicate_run_id")

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


def _resolve_routing(
    ctx: "DispatchContext",
    event: "PipelineEvent",
    clean_body: str,
) -> tuple[str | None, StageName, DispatchResult | None]:
    """Resolve target stage + optional user_prompt override.

    Three paths:
    - Feedback event: assemble context from handovers + comments, route
      to the stage feedback maps to. May short-circuit if a handover is
      newer than all pending feedback (already addressed).
    - Proceed (no trigger_stage): advance past the current gate.
    - Explicit trigger_stage: use as-is.
    """
    if event.is_feedback:
        issue_handover = ctx.work.find_last_handover(event.key)
        pr_handover = None
        pr_diff = None
        if event.pr_number:
            pr_handover = ctx.review.find_last_handover(event.pr_number)
            pr_diff = ctx.review.read_pr_diff(event.pr_number)

        handover = pick_handover(issue_handover, pr_handover)
        since = handover.created_at if handover else datetime.min

        context = assemble_context(
            ticket_body=clean_body,
            issue_handover=issue_handover,
            pr_handover=pr_handover,
            issue_feedback=ctx.work.collect_issue_feedback(event.key, since),
            pr_feedback=(
                ctx.review.collect_pr_feedback(event.pr_number, since)
                if event.pr_number
                else []
            ),
            pr_diff=pr_diff,
        )

        # Dedup: skip if handover is newer than all feedback.
        if context.feedback and not context.is_first_run:
            newest_feedback = max(f.created_at for f in context.feedback)
            if handover and handover.created_at > newest_feedback:
                ctx.logger.info("dispatch.feedback_already_addressed")
                return (
                    None,
                    context.current_stage or StageName.SPEC,
                    DispatchResult(
                        stage=context.current_stage or StageName.SPEC,
                        error="feedback_already_addressed",
                    ),
                )

        target_stage = resolve_target_stage(context.current_stage)
        return context.user_prompt, target_stage, None

    if event.trigger_stage is None:
        # Proceed: advance past current gate.
        issue_handover = ctx.work.find_last_handover(event.key)
        current_stage = issue_handover.stage if issue_handover else None
        if current_stage == StageName.SPEC:
            return None, StageName.IMPLEMENT, None
        if current_stage == StageName.REVIEW:
            return None, StageName.MERGE, None
        return None, StageName.IMPLEMENT, None  # fallback

    return None, event.trigger_stage, None


__all__ = ["PreflightOutcome", "PreflightResult", "run_preflight"]
