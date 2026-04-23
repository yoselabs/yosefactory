"""Preflight — thin composition over ``ingress`` + ``gating``.

Post-P4-step-5 this module is a transitional shim that preserves the
``run_preflight(ctx) -> PreflightResult`` signature for legacy call
sites (stage tests, standalone-invocability harness). ``dispatch.py``
no longer routes through it; it calls ``ingress.parse_event`` +
``gating.check`` + ``ingress.resolve_intent`` directly.

The module will be deleted in P4 step 9 once remaining callers migrate
to the new surface (or a one-line shim is inlined where it helps).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.pipeline.gating import check_ticket_active
from a2sdlc.pipeline.ingress import ParsedSkip, parse_event, resolve_intent

if TYPE_CHECKING:
    from a2sdlc.pipeline.dispatch import DispatchContext


# Transitional alias — P4 step 4. ``PreflightOutcome`` was renamed +
# relocated to ``domain.run_intent.RunIntent``; the alias keeps legacy
# call sites compiling until step 9 removes it.
PreflightOutcome = RunIntent

PreflightResult = Union[RunIntent, DispatchResult]


def run_preflight(ctx: "DispatchContext") -> PreflightResult:
    """Resolve the stage to run + all inputs, or short-circuit.

    Composition shim: ``parse_event`` → ticket-closed → ticket-active →
    ``resolve_intent``. Kept for test callers; ``dispatch.dispatch``
    calls these primitives directly.
    """
    parsed = parse_event(ctx)
    if isinstance(parsed, ParsedSkip):
        return DispatchResult(stage=StageName.SPEC, error=parsed.reason)

    event = parsed
    if event.is_closed:
        ctx.logger.info("dispatch.ticket_closed", extra={"key": event.key})
        ctx.work.mark_done(event.key)
        return DispatchResult(stage=StageName.MERGE, error="ticket_closed")

    if reason := check_ticket_active(ctx, event):
        return DispatchResult(stage=StageName.SPEC, error=reason)

    return resolve_intent(ctx, event)


__all__ = ["PreflightOutcome", "PreflightResult", "run_preflight"]
