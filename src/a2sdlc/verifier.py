"""Verifier — Pydantic-based post-condition checks and stage routing."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.base import CodeAdapter, TicketAdapter
from a2sdlc.config import ProjectConfig
from a2sdlc.models import StageStatus, extract_result, strip_status_block
from a2sdlc.runner import RunResult, format_cost

logger = logging.getLogger("a2sdlc.verifier")


def verify_and_act(
    stage: str,
    result: RunResult,
    ticket_key: str,
    tickets: TicketAdapter,
    code: CodeAdapter,
    project: ProjectConfig,
    comment_id: str = "",
) -> None:
    """Post-condition checks and deterministic actions per stage."""
    cost_footer = format_cost(result)

    if not result.success:
        _post(
            tickets,
            ticket_key,
            comment_id,
            f"🚨 Error in **{stage}** stage: `{result.error}`\n\n{cost_footer}",
        )
        return

    stage_result = extract_result(result.output)
    comment_body = strip_status_block(result.output)

    if stage_result is None:
        _post(
            tickets,
            ticket_key,
            comment_id,
            f"⚠️ No status block in **{stage}** output.\n\n{comment_body[:2000]}\n\n{cost_footer}",
        )
        return

    logger.info("Stage %s status: %s", stage, stage_result.status)

    match (stage, stage_result.status):
        case ("spec", StageStatus.COMPLETE):
            _handle_spec_complete(
                tickets, ticket_key, comment_id, comment_body, cost_footer
            )
        case ("spec", StageStatus.QUESTIONS):
            _handle_questions(
                tickets, ticket_key, comment_id, comment_body, cost_footer
            )
        case ("implement", StageStatus.COMPLETE):
            _handle_implement_complete(
                tickets, ticket_key, comment_id, comment_body, cost_footer
            )
        case ("implement", StageStatus.QUESTIONS):
            _handle_questions(
                tickets, ticket_key, comment_id, comment_body, cost_footer
            )
        case ("review", StageStatus.APPROVED):
            _handle_review_approved(
                tickets,
                code,
                ticket_key,
                comment_id,
                comment_body,
                cost_footer,
                project,
            )
        case ("review", StageStatus.CHANGES_REQUESTED):
            _handle_review_changes(
                tickets, ticket_key, comment_id, comment_body, cost_footer
            )
        case _:
            _post(
                tickets,
                ticket_key,
                comment_id,
                f"⚠️ Unexpected ({stage}, {stage_result.status})\n\n{cost_footer}",
            )


# ── Handlers ─────────────────────────────────────────────────────────


def _handle_spec_complete(
    tickets: TicketAdapter,
    ticket_key: str,
    comment_id: str,
    comment_body: str,
    cost_footer: str,
) -> None:
    _write_state("spec", "complete")
    _post(tickets, ticket_key, comment_id, f"{comment_body}\n\n{cost_footer}")
    logger.info("Spec complete for %s", ticket_key)


def _handle_questions(
    tickets: TicketAdapter,
    ticket_key: str,
    comment_id: str,
    comment_body: str,
    cost_footer: str,
) -> None:
    _post(tickets, ticket_key, comment_id, f"{comment_body}\n\n{cost_footer}")
    tickets.transition(ticket_key, "needs-input")
    logger.info("Questions posted, transitioned %s to needs-input", ticket_key)


def _handle_implement_complete(
    tickets: TicketAdapter,
    ticket_key: str,
    comment_id: str,
    comment_body: str,
    cost_footer: str,
) -> None:
    _write_state("implement", "complete")
    _post(tickets, ticket_key, comment_id, f"{comment_body}\n\n{cost_footer}")
    logger.info("Implementation complete for %s", ticket_key)


def _handle_review_approved(
    tickets: TicketAdapter,
    code: CodeAdapter,
    ticket_key: str,
    comment_id: str,
    comment_body: str,
    cost_footer: str,
    project: ProjectConfig,
) -> None:
    _post(tickets, ticket_key, comment_id, f"{comment_body}\n\n{cost_footer}")
    logger.info("Review approved for %s", ticket_key)
    if project.auto_merge:
        try:
            pr_number = int(ticket_key)
            logger.info("Auto-merge enabled, merging PR #%d", pr_number)
            code.merge_pr(pr_number)
        except (ValueError, TypeError):
            logger.warning(
                "Auto-merge skipped: ticket_key %r is not a PR number", ticket_key
            )


def _handle_review_changes(
    tickets: TicketAdapter,
    ticket_key: str,
    comment_id: str,
    comment_body: str,
    cost_footer: str,
) -> None:
    _post(tickets, ticket_key, comment_id, f"{comment_body}\n\n{cost_footer}")
    tickets.transition(ticket_key, "needs-fix")
    logger.info("Review requested changes for %s, added needs-fix", ticket_key)


# ── Helpers ──────────────────────────────────────────────────────────


def _post(
    tickets: TicketAdapter,
    ticket_key: str,
    comment_id: str,
    body: str,
) -> None:
    if comment_id:
        tickets.update_comment(ticket_key, comment_id, body)
    else:
        tickets.create_comment(ticket_key, body)


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
