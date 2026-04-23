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

from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.pipeline.context import assemble_context, pick_handover
from a2sdlc.pipeline.feedback_routing import resolve_target_stage

if TYPE_CHECKING:
    from a2sdlc.domain.pipeline_event import PipelineEvent
    from a2sdlc.pipeline.dispatch import DispatchContext


@dataclass(frozen=True)
class ParsedSkip:
    """Sentinel returned by ``parse_event`` when the WorkAdapter said skip.

    The composition root converts this into a ``DispatchResult`` with
    ``error=reason``. Kept as a dataclass rather than a plain ``None``
    so dispatch can pattern-match and preserve the skip label for
    telemetry.
    """

    reason: str


def parse_event(ctx: "DispatchContext") -> "PipelineEvent | ParsedSkip":
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


__all__ = ["ParsedSkip", "parse_event", "resolve_routing"]
