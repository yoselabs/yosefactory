"""Ingress — event parsing and intent resolution.

Owns the "what does this dispatch invocation mean?" boundary:

- ``parse_event(ctx)`` — thin wrapper over ``WorkAdapter.parse_event``
  that converts the ``SkipEvent`` exception into a ``ParsedSkip``
  discriminant. Logs structured skips so the composition root doesn't
  have to.
- ``resolve_routing(ctx, event, clean_body)`` — determines target stage
  + user-prompt override. Three paths: feedback event (handover context
  assembly, routes to the stage the feedback maps to), proceed event
  (no trigger_stage, advance past current gate), explicit trigger_stage
  event (use as-is). Migrated from ``preflight._resolve_routing`` in
  P4 step 2.

P4 later steps extend this with full ``resolve_intent`` (intent-
building) and collapse ``preflight.py`` once gating moves out too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from a2sdlc.config import load_stage_config
from a2sdlc.domain.directives import (
    merge_directives,
    parse_directives,
    parse_label_directives,
)
from a2sdlc.domain.exceptions import BlockedError, SkipEvent
from a2sdlc.domain.models import GateConfig, StageName
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.lifecycle.state import StateManager
from a2sdlc.lifecycle.state_storage import GitFileStateStorage
from a2sdlc.ingress.context import assemble_context, pick_handover
from a2sdlc.ingress.feedback_routing import resolve_target_stage
from a2sdlc.gating import check_cost_ceiling, check_review_cycles

if TYPE_CHECKING:
    from a2sdlc.domain.pipeline_event import PipelineEvent
    from a2sdlc.domain.run_context import RunContext


@dataclass(frozen=True)
class ParsedSkip:
    """Sentinel returned by ``parse_event`` when the WorkAdapter said skip.

    The composition root converts this into a ``DispatchResult`` with
    ``error=reason``. Kept as a dataclass rather than a plain ``None``
    so dispatch can pattern-match and preserve the skip label for
    telemetry.
    """

    reason: str


def parse_event(ctx: "RunContext") -> "PipelineEvent | ParsedSkip":
    """Parse the current dispatch event off the work adapter.

    Returns the ``PipelineEvent`` on success, or ``ParsedSkip(reason)``
    when ``WorkAdapter.parse_event`` raises ``SkipEvent`` (stale label
    drag, unrecognized event payload, etc.).
    """
    try:
        return ctx.work.parse_event()
    except SkipEvent as e:
        ctx.logger.info("dispatch.skip", extra={"reason": e.reason})
        return ParsedSkip(reason=e.reason)


def resolve_routing(
    ctx: "RunContext",
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

    Returns ``(user_prompt_override, target_stage, short_circuit_result)``.
    When ``short_circuit_result`` is non-None, dispatch returns it
    directly without running the stage.
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


def resolve_intent(
    ctx: "RunContext",
    event: "PipelineEvent",
) -> "RunIntent | DispatchResult":
    """Build the ``RunIntent`` for ``event``, or short-circuit.

    Runs after ``parse_event`` + ``gating.check_ticket_active`` — handles
    directive parsing, routing, branch setup, state read, and circuit
    breakers. Returns a ``DispatchResult`` when git setup is blocked
    or a circuit breaker trips. Idempotency is enforced by the
    ``with_idempotency`` middleware downstream; it needs this function
    to have resolved ``intent.state_mgr`` first.
    """
    ticket_body = ctx.work.get_ticket(event.key)
    body_directives, clean_body = parse_directives(ticket_body)
    # Re-read labels fresh each dispatch — webhook event payload only
    # carries the *triggering* label, not the current set. A user who
    # adds `gate:merge:human` after the `agent` label has already fired
    # the run still expects that gate honored on the next stage.
    live_labels = ctx.work.get_labels(event.key)
    label_directives = parse_label_directives(live_labels)
    directives = merge_directives(label_directives, body_directives)

    user_prompt_override, target_stage, routing_result = resolve_routing(
        ctx, event, clean_body
    )
    if routing_result is not None:
        return routing_result

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

    state = state_mgr.read_state()

    stage_cfg = load_stage_config(target_stage.value, ctx.config)
    for reason in (
        check_review_cycles(target_stage, state, stage_cfg),
        check_cost_ceiling(state, ctx.config),
    ):
        if reason is not None:
            ctx.logger.error("dispatch.circuit_breaker", extra={"reason": reason})
            ctx.work.mark_blocked(event.key, reason)
            return DispatchResult(stage=target_stage, blocked=True, error=reason)

    return RunIntent(
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


__all__ = ["ParsedSkip", "parse_event", "resolve_intent", "resolve_routing"]
