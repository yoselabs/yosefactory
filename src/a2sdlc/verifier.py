"""Verifier — extract artifacts, check markers, post-condition enforcement."""

from __future__ import annotations

import logging
import re

from a2sdlc.adapters.base import CodeAdapter, TicketAdapter

logger = logging.getLogger("a2sdlc.verifier")

# Markers that use the A2SDLC: prefix.
_A2SDLC_MARKERS = {"PRD", "PLAN", "REVIEW"}


def extract_artifact(output: str, marker: str) -> str:
    """Extract content between a marker heading and the next ``##`` heading or end of string."""
    if marker in _A2SDLC_MARKERS:
        pattern = rf"##\s*\[?A2SDLC:{re.escape(marker)}\]?\s*\n(.*?)(?=\n##\s|\Z)"
    else:
        pattern = rf"##\s*{re.escape(marker)}\s*\n(.*?)(?=\n##\s|\Z)"

    match = re.search(pattern, output, re.DOTALL)
    return match.group(1).strip() if match else ""


def check_markers(output: str) -> dict[str, bool]:
    """Check which markers are present in the output."""
    return {
        "has_prd": bool(re.search(r"##\s*\[A2SDLC:PRD\]", output)),
        "has_questions": bool(re.search(r"##\s*Questions", output)),
        "has_plan": bool(re.search(r"##\s*\[A2SDLC:PLAN\]", output)),
        "has_review": bool(re.search(r"##\s*\[A2SDLC:REVIEW\]", output)),
    }


def verify_and_act(
    stage: str,
    result: dict,
    ticket_key: str,
    tickets: TicketAdapter,
    code: CodeAdapter,
    supervised: bool = False,
    comment_id: str = "",
) -> None:
    """Post-condition checks and deterministic actions per stage."""
    if not result.get("success"):
        error = result.get("error", "unknown")
        if comment_id:
            tickets.update_comment(
                ticket_key, comment_id, f"🚨 Error in **{stage}** stage: `{error}`"
            )
        else:
            tickets.create_comment(
                ticket_key, f"🚨 Error in **{stage}** stage: `{error}`"
            )
        return

    output = str(result.get("output", ""))
    markers = check_markers(output)
    logger.info("Stage %s markers: %s", stage, markers)

    if stage == "prd":
        _verify_prd(output, markers, ticket_key, tickets, supervised, comment_id)
    elif stage == "plan":
        _verify_plan(output, markers, ticket_key, tickets, supervised, comment_id)
    else:
        logger.info("verify_and_act not yet implemented for stage %s", stage)


def _verify_prd(
    output: str,
    markers: dict[str, bool],
    ticket_key: str,
    tickets: TicketAdapter,
    supervised: bool,
    comment_id: str = "",
) -> None:
    def _update(body: str) -> None:
        if comment_id:
            tickets.update_comment(ticket_key, comment_id, body)
        else:
            tickets.create_comment(ticket_key, body)

    if markers["has_questions"]:
        questions = extract_artifact(output, "Questions")
        _update(f"❓ PRD Agent needs clarification\n\n{questions}")
        tickets.transition(ticket_key, "needs-input")
        logger.info("PRD has questions, transitioned %s to needs-input", ticket_key)
    elif markers["has_prd"]:
        prd = extract_artifact(output, "PRD")
        _update(f"✅ PRD Complete\n\n{prd}")
        tickets.transition(ticket_key, "prd-complete")
        logger.info("PRD complete, transitioned %s to prd-complete", ticket_key)
        if not supervised:
            tickets.trigger_next("prd-approved", {"key": ticket_key})
    else:
        truncated = output[:2000]
        tickets.create_comment(
            ticket_key,
            f"⚠️ Warning: PRD stage produced no recognized markers.\n\n```\n{truncated}\n```",
        )
        logger.warning("PRD stage output has no recognized markers for %s", ticket_key)


def _verify_plan(
    output: str,
    markers: dict[str, bool],
    ticket_key: str,
    tickets: TicketAdapter,
    supervised: bool,
    comment_id: str = "",
) -> None:
    def _update(body: str) -> None:
        if comment_id:
            tickets.update_comment(ticket_key, comment_id, body)
        else:
            tickets.create_comment(ticket_key, body)

    if markers["has_plan"]:
        plan = extract_artifact(output, "PLAN")
        _update(f"✅ Plan Complete\n\n{plan}")
        tickets.transition(ticket_key, "plan-complete")
        logger.info("Plan complete, transitioned %s to plan-complete", ticket_key)
        if not supervised:
            tickets.trigger_next("plan-approved", {"key": ticket_key})
