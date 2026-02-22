"""Verifier — stage-driven routing logic + action execution."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.base import CodeAdapter, TicketAdapter
from a2sdlc.config import ProjectConfig
from a2sdlc.models import StageAction, extract_result, strip_status_block
from a2sdlc.runner import RunResult, format_cost
from a2sdlc.stages import get_stage

logger = logging.getLogger("a2sdlc.verifier")


# ── Pure routing ────────────────────────────────────────────────────


def resolve_action(
    stage_name: str,
    result: RunResult,
    project: ProjectConfig,
    pr_number: int | None = None,
) -> StageAction:
    """Determine what action to take based on stage + result.

    Pure function — no I/O, no side effects.
    """
    cost_footer = format_cost(result)

    if not result.success:
        return StageAction(
            comment=f"🚨 Error in **{stage_name}** stage: `{result.error}`\n\n{cost_footer}",
        )

    stage_result = extract_result(result.output)
    comment_body = strip_status_block(result.output)

    if stage_result is None:
        return StageAction(
            comment=(
                f"⚠️ No status block in **{stage_name}** output."
                f"\n\n{comment_body[:2000]}\n\n{cost_footer}"
            ),
        )

    stage = get_stage(stage_name)

    if stage_result.status not in stage.valid_statuses:
        return StageAction(
            comment=(
                f"⚠️ Unexpected status `{stage_result.status}` for **{stage_name}**."
                f"\n\n{cost_footer}"
            ),
        )

    # Build stage-specific kwargs.
    kwargs: dict[str, object] = {}
    if stage_name == "review":
        kwargs["auto_merge"] = project.auto_merge
        kwargs["pr_number"] = pr_number

    return stage.resolve(stage_result.status, comment_body, cost_footer, **kwargs)


# ── Action execution ────────────────────────────────────────────────


def execute_action(
    action: StageAction,
    ticket_key: str,
    tickets: TicketAdapter,
    code: CodeAdapter,
    comment_id: str = "",
) -> None:
    """Apply a StageAction — post comments, set labels, merge PRs."""
    if comment_id:
        tickets.update_comment(ticket_key, comment_id, action.comment)
    else:
        tickets.create_comment(ticket_key, action.comment)

    if action.transition_to:
        tickets.transition(ticket_key, action.transition_to)
        logger.info("Transitioned %s to %s", ticket_key, action.transition_to)

    if action.write_state:
        _write_state(*action.write_state)

    if action.merge_pr is not None:
        logger.info("Auto-merging PR #%d", action.merge_pr)
        code.merge_pr(action.merge_pr)


# ── Entry point ─────────────────────────────────────────────────────


def verify_and_act(
    stage: str,
    result: RunResult,
    ticket_key: str,
    tickets: TicketAdapter,
    code: CodeAdapter,
    project: ProjectConfig,
    comment_id: str = "",
    pr_number: int | None = None,
) -> None:
    """Resolve action from result, then execute it."""
    action = resolve_action(stage, result, project, pr_number)
    logger.info("Stage %s action: %s", stage, action)
    execute_action(action, ticket_key, tickets, code, comment_id)


# ── Helpers ──────────────────────────────────────────────────────────


def _write_state(stage: str, status: str) -> None:
    """Write .a2sdlc/state.json on the current branch."""
    state = {
        "stage": stage,
        "status": status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    state_path = Path(".a2sdlc/state.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
    logger.info("Wrote state: %s", state)
