"""WorkAdapter Protocol + PipelineEvent + in-tree work impls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName


@dataclass
class PipelineEvent:
    """Normalized pipeline event from a work adapter.

    trigger_stage: what the event literally says (label value, or None for feedback/proceed).
    is_feedback: True for comment/review events, False for label events.
    The engine resolves the actual target stage via the routing table.
    """

    key: str
    trigger_stage: StageName | None = None
    is_feedback: bool = False
    pr_number: int | None = None


class WorkAdapter(Protocol):
    """Platform-specific ticket/work-item operations."""

    def parse_event(self) -> PipelineEvent: ...
    def get_ticket(self, key: str) -> str: ...
    def get_labels(self, key: str) -> list[str]: ...
    def begin_comment(self, key: str) -> str: ...
    def update_progress(self, comment_id: str, body: str) -> None: ...
    def finalize_comment(self, comment_id: str, body: str) -> None: ...
    def set_stage_label(self, key: str, stage: StageName) -> None: ...
    def set_done_label(self, key: str) -> None: ...
    def set_blocked(self, key: str, reason: str) -> None: ...
    def format_branch(self, ticket_key: str) -> str: ...
    def collect_issue_feedback(
        self, key: str, since: datetime
    ) -> list[FeedbackItem]: ...
    def find_last_handover(self, key: str) -> HandoverComment | None: ...


# NOTE: impls below import PipelineEvent (and WorkAdapter) from this module.
# That works because Python sees those names as already-defined when it
# executes the import statements below. Keep these re-exports LAST —
# moving them above the dataclass/Protocol definitions above would break
# the partial-init chain with ImportError.
from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter  # noqa: E402
from a2sdlc.adapters.work.github import GitHubWorkAdapter  # noqa: E402

__all__ = ["PipelineEvent", "WorkAdapter", "LocalFileWorkAdapter", "GitHubWorkAdapter"]
