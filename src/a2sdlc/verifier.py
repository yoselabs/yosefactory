"""Verifier — pure routing logic + action execution."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.base import CodeAdapter, TicketAdapter
from a2sdlc.config import ProjectConfig
from a2sdlc.models import StageAction, StageStatus, extract_result, strip_status_block
from a2sdlc.runner import RunResult, format_cost

logger = logging.getLogger("a2sdlc.verifier")


# ── Pure routing — no side effects ──────────────────────────────────


def resolve_action(
    stage: str,
    result: RunResult,
    project: ProjectConfig,
) -> StageAction:
    """Determine what action to take based on stage + result.

    Pure function — no I/O, no side effects. Returns a StageAction
    that describes what should happen. Testable without mocking.
    """
    cost_footer = format_cost(result)

    if not result.success:
        return StageAction(
            comment=f"🚨 Error in **{stage}** stage: `{result.error}`\n\n{cost_footer}",
        )

    stage_result = extract_result(result.output)
    comment_body = strip_status_block(result.output)

    if stage_result is None:
        return StageAction(
            comment=(
                f"⚠️ No status block in **{stage}** output."
                f"\n\n{comment_body[:2000]}\n\n{cost_footer}"
            ),
        )

    match (stage, stage_result.status):
        case ("spec", StageStatus.COMPLETE):
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                write_state=("spec", "complete"),
            )
        case (_, StageStatus.QUESTIONS):
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                transition_to="needs-input",
            )
        case ("implement", StageStatus.COMPLETE):
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                write_state=("implement", "complete"),
            )
        case ("review", StageStatus.APPROVED):
            action = StageAction(comment=f"{comment_body}\n\n{cost_footer}")
            if project.auto_merge:
                try:
                    action.merge_pr = int("0")  # placeholder — see verify_and_act
                except ValueError:
                    pass
            return action
        case ("review", StageStatus.CHANGES_REQUESTED):
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                transition_to="needs-fix",
            )
        case _:
            return StageAction(
                comment=(
                    f"⚠️ Unexpected ({stage}, {stage_result.status})\n\n{cost_footer}"
                ),
            )


# ── Action execution — side effects happen here ─────────────────────


def execute_action(
    action: StageAction,
    ticket_key: str,
    tickets: TicketAdapter,
    code: CodeAdapter,
    comment_id: str = "",
) -> None:
    """Apply a StageAction — post comments, set labels, merge PRs."""
    # Post comment.
    if comment_id:
        tickets.update_comment(ticket_key, comment_id, action.comment)
    else:
        tickets.create_comment(ticket_key, action.comment)

    # Transition label.
    if action.transition_to:
        tickets.transition(ticket_key, action.transition_to)
        logger.info("Transitioned %s to %s", ticket_key, action.transition_to)

    # Write state file.
    if action.write_state:
        _write_state(*action.write_state)

    # Merge PR.
    if action.merge_pr is not None:
        logger.info("Auto-merging PR #%d", action.merge_pr)
        code.merge_pr(action.merge_pr)


# ── Top-level entry point ───────────────────────────────────────────


def verify_and_act(
    stage: str,
    result: RunResult,
    ticket_key: str,
    tickets: TicketAdapter,
    code: CodeAdapter,
    project: ProjectConfig,
    comment_id: str = "",
) -> None:
    """Resolve action from result, then execute it."""
    action = resolve_action(stage, result, project)

    # Fix up merge_pr with actual ticket key (resolve_action is pure,
    # doesn't have ticket_key).
    stage_result = extract_result(result.output)
    if action.merge_pr is not None or (
        stage == "review"
        and project.auto_merge
        and stage_result is not None
        and stage_result.status == StageStatus.APPROVED
    ):
        try:
            action.merge_pr = int(ticket_key)
        except (ValueError, TypeError):
            logger.warning(
                "Auto-merge skipped: ticket_key %r is not a PR number", ticket_key
            )
            action.merge_pr = None

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
