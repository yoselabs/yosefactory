"""Handover comment types and pattern matching.

The handover pattern is compiled from StageName — adding a stage
automatically updates the pattern. StageName is the single source
of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from a2sdlc.domain.models import StageName

HANDOVER_PREFIX = "a2sdlc:"
HANDOVER_PATTERN = re.compile(
    rf"{re.escape(HANDOVER_PREFIX)}({'|'.join(re.escape(s.value) for s in StageName)})"
)

_STAGE_ORDER: dict[StageName, int] = {s: i for i, s in enumerate(StageName)}


def later_stage(a: StageName, b: StageName) -> StageName:
    """Return whichever stage comes later in the pipeline."""
    return a if _STAGE_ORDER[a] >= _STAGE_ORDER[b] else b


@dataclass(frozen=True)
class FeedbackItem:
    """A single feedback comment from any source."""

    id: str
    author: str
    author_type: str  # "human" | "bot"
    source: str  # "issue_comment" | "pr_comment" | "pr_inline" | "pr_review"
    body: str
    created_at: datetime
    file_path: str | None = None
    line_range: tuple[int, int] | None = None


@dataclass(frozen=True)
class HandoverComment:
    """A parsed handover comment from an issue or PR."""

    stage: StageName
    run_id: str
    body: str
    created_at: datetime
    location: str  # "issue" | "pr"


def parse_handover(
    comment_body: str, comment_id: str, created_at: datetime, location: str
) -> HandoverComment | None:
    """Try to parse a comment as a handover. Returns None if not a handover."""
    match = HANDOVER_PATTERN.search(comment_body)
    if match is None:
        return None
    stage = StageName(match.group(1))
    return HandoverComment(
        stage=stage,
        run_id=comment_id,
        body=comment_body,
        created_at=created_at,
        location=location,
    )
