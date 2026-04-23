"""Stage-finish helpers — translate handler outcomes for dispatch.

Extracted from ``pipeline.dispatch`` in P4 step 8 so the composition
root stays focused on wiring. Pure functions over ``RunIntent`` +
``StageOutcome``; no ctx, no I/O.

Two paths feed ``stage_end`` telemetry:

- Pause: ``MarkBlocked`` / ``AwaitHumanDecision`` in the effect list
  signals a non-advance — surfaced as ``success=False`` with a
  reason label.
- Advance: merged (MERGE happy path, no status) or status-bearing
  AI-stage outcome.
"""

from __future__ import annotations

from collections.abc import Sequence

from a2sdlc.domain.effects import AwaitHumanDecision, Effect, MarkBlocked
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.domain.stage_outcome import StageOutcome

_PAUSE_ARMS = (MarkBlocked, AwaitHumanDecision)


def pipeline_pause_reason(effects: Sequence[Effect]) -> str | None:
    """Return the pause-reason label if the effect list signals a non-advance."""
    for eff in effects:
        if isinstance(eff, _PAUSE_ARMS):
            return eff.reason
    return None


def outcome_to_dispatch_tuple(
    pre: RunIntent, outcome: StageOutcome
) -> tuple[DispatchResult, bool, str | None]:
    """Translate a handler's StageOutcome into dispatch's tuple shape."""
    pause_reason = pipeline_pause_reason(outcome.prepared_effects)
    if pause_reason is not None:
        return (
            DispatchResult(
                stage=pre.target_stage,
                blocked=True,
                error=pause_reason,
                output=outcome.output_text,
            ),
            False,
            pause_reason,
        )
    if outcome.merged:
        return (DispatchResult(stage=pre.target_stage), True, None)
    assert outcome.status is not None, "non-paused StageOutcome must carry a status"  # noqa: S101
    return (
        DispatchResult(
            stage=pre.target_stage,
            status=outcome.status,
            next_stage=outcome.next_stage_hint,
            blocked=False,
            stats=outcome.stats,
            output=outcome.output_text,
        ),
        True,
        None,
    )


__all__ = ["outcome_to_dispatch_tuple", "pipeline_pause_reason"]
