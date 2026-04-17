"""Uniform context assembly — finds handover, collects feedback, builds prompt."""

from __future__ import annotations

from dataclasses import dataclass

from a2sdlc.domain.handover import FeedbackItem, HandoverComment, later_stage
from a2sdlc.domain.models import StageName


@dataclass
class ContextResult:
    """Output of context assembly."""

    user_prompt: str
    feedback: list[FeedbackItem]
    current_stage: StageName | None
    is_first_run: bool


def pick_handover(
    issue_ho: HandoverComment | None,
    pr_ho: HandoverComment | None,
) -> HandoverComment | None:
    """Pick the most recent handover, tie-breaking by pipeline stage order."""
    if issue_ho is None:
        return pr_ho
    if pr_ho is None:
        return issue_ho
    if issue_ho.created_at > pr_ho.created_at:
        return issue_ho
    if pr_ho.created_at > issue_ho.created_at:
        return pr_ho
    # Same timestamp — prefer later pipeline stage
    winner_stage = later_stage(issue_ho.stage, pr_ho.stage)
    return pr_ho if pr_ho.stage == winner_stage else issue_ho


def _format_feedback_section(items: list[FeedbackItem]) -> str:
    """Format feedback items as markdown for the agent prompt."""
    if not items:
        return ""

    lines = ["## Feedback to Address\n"]
    for item in sorted(items, key=lambda f: f.created_at):
        header = f"### {item.source} by @{item.author}"
        lines.append(header)
        if item.file_path:
            loc = f"`{item.file_path}`"
            if item.line_range:
                loc += f" lines {item.line_range[0]}-{item.line_range[1]}"
            lines.append(f"- {loc}: {item.body}")
        else:
            lines.append(item.body)
        lines.append("")
    return "\n".join(lines)


def assemble_context(
    *,
    ticket_body: str,
    issue_handover: HandoverComment | None,
    pr_handover: HandoverComment | None,
    issue_feedback: list[FeedbackItem],
    pr_feedback: list[FeedbackItem],
    pr_diff: str | None,
) -> ContextResult:
    """Uniform context assembly — one code path for all scenarios.

    1. Pick the most recent handover (issue or PR, tie-break by stage order).
    2. Combine all feedback.
    3. Build prompt: ticket body + handover body + feedback + PR diff.
    """
    handover = pick_handover(issue_handover, pr_handover)

    all_feedback = issue_feedback + pr_feedback
    all_feedback.sort(key=lambda f: f.created_at)

    parts: list[str] = [ticket_body]

    if handover is not None:
        parts.append(handover.body)

    feedback_section = _format_feedback_section(all_feedback)
    if feedback_section:
        parts.append(feedback_section)

    if pr_diff:
        parts.append(f"## Current PR Diff\n\n{pr_diff}")

    return ContextResult(
        user_prompt="\n\n".join(parts),
        feedback=all_feedback,
        current_stage=handover.stage if handover else None,
        is_first_run=handover is None,
    )
