"""Work adapter protocol — ticket/issue operations for pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from a2sdlc.models import StageName


@dataclass(frozen=True)
class PipelineEvent:
    """Normalized event from the work adapter. Platform-agnostic."""

    key: str
    stage: StageName
    labels: frozenset[str] = field(default_factory=frozenset)
    is_resume: bool = False
    pr_number: int | None = None


class WorkAdapter(Protocol):
    """Platform-specific work item (ticket/issue) operations.

    Compared to TicketAdapter, WorkAdapter splits concerns more cleanly:
    - Comment lifecycle: begin_comment / update_progress / finalize_comment
    - Labels: set_label
    - Blocking: set_blocked
    - Event parsing: parse_event / get_ticket / get_labels
    - Branch naming: format_branch
    """

    def parse_event(self) -> PipelineEvent:
        """Parse incoming platform event into a PipelineEvent.

        Raises SkipEvent if the event is not actionable.
        """
        ...

    def get_ticket(self, key: str) -> str:
        """Return the issue/ticket body for the given key."""
        ...

    def get_labels(self, key: str) -> list[str]:
        """Return current label names for the given key."""
        ...

    def begin_comment(self, key: str) -> str:
        """Post an initial 'started' comment and return its comment ID."""
        ...

    def update_progress(self, comment_id: str, body: str) -> None:
        """Update an in-progress comment with new body text."""
        ...

    def finalize_comment(self, comment_id: str, body: str) -> None:
        """Replace comment body with the final result text."""
        ...

    def set_label(self, key: str, label: str) -> None:
        """Set a label on the work item (replaces any existing stage label)."""
        ...

    def set_blocked(self, key: str, reason: str) -> None:
        """Mark the work item as blocked with a reason."""
        ...

    def format_branch(self, ticket_key: str) -> str:
        """Return the branch name convention for this adapter.

        Example: ``agent/PROJ-123``
        """
        ...
