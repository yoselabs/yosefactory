"""Circuit-breaker checks that gate stage execution on accumulated state.

Each breaker returns a `reason` string when tripped, or None to proceed.
Dispatch then calls `work.mark_blocked(key, reason)` and bails early —
the engine never re-runs a stage for a ticket already past its limits.
"""

from __future__ import annotations

from a2sdlc.config import ProjectConfig, StageConfig
from a2sdlc.domain.models import StageName, TicketState


def check_review_cycles(
    target_stage: StageName, state: TicketState | None, stage_cfg: StageConfig
) -> str | None:
    """Trip when REVIEW has looped ≥ max_review_cycles times.

    Only runs for REVIEW; other stages pass through.
    """
    if target_stage != StageName.REVIEW:
        return None
    cycles = state.review_cycles if state else 0
    if cycles >= stage_cfg.max_review_cycles:
        return (
            f"Circuit breaker: {cycles} review cycles "
            f"exceeded max ({stage_cfg.max_review_cycles})"
        )
    return None


def check_cost_ceiling(state: TicketState | None, config: ProjectConfig) -> str | None:
    """Trip when accumulated per-ticket spend exceeds max_cost_usd_per_ticket.

    Applies to every stage — a chatty SPEC can burn budget just as fast
    as a looping REVIEW.
    """
    spent = state.accumulated_cost_usd if state else 0.0
    ceiling = config.max_cost_usd_per_ticket
    if spent >= ceiling:
        return f"Cost ceiling: ${spent:.2f} >= ${ceiling:.2f} per-ticket max"
    return None
