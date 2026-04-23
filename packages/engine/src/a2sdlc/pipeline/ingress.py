"""Ingress — event parsing and intent resolution.

Owns the "what does this dispatch invocation mean?" boundary. Today
handles:

- ``parse_event(ctx)`` — thin wrapper over ``WorkAdapter.parse_event``
  that converts the ``SkipEvent`` exception into a ``ParsedSkip``
  discriminant. Logs structured skips so the composition root doesn't
  have to.

P4 step 2 will add ``resolve_intent(ctx, event) -> RunIntent`` (routing
logic migrated from ``preflight._resolve_routing``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from a2sdlc.domain.exceptions import SkipEvent

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


__all__ = ["ParsedSkip", "parse_event"]
