"""Adapter protocols — platform-agnostic interfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName
from a2sdlc.runner import RunResult


@dataclass(frozen=True)
class DispatchInput:
    """Normalized event from the adapter. Platform-agnostic."""

    key: str
    stage: StageName
    labels: frozenset[str] = frozenset()
    is_resume: bool = False
    pr_number: int | None = None


class TicketAdapter(Protocol):
    """Platform-specific ticket operations."""

    STAGE_LABELS: dict[StageName, str]
    TRIGGER_LABEL: str
    BLOCKED_LABEL: str
    DONE_LABEL: str
    NEEDS_INPUT_LABEL: str
    PROCEED_LABEL: str

    def parse_event(self) -> DispatchInput: ...
    def get_ticket(self, key: str) -> str: ...
    def get_labels(self, key: str) -> list[str]: ...
    def post_comment(self, key: str, body: str) -> str: ...
    def update_comment(self, key: str, comment_id: str, body: str) -> None: ...
    def set_stage_label(self, key: str, stage: StageName) -> None: ...
    def set_done_label(self, key: str) -> None: ...
    def set_blocked(self, key: str, reason: str) -> None: ...
    def post_review(self, pr: int, body: str, event: str) -> None: ...
    def get_pr_for_branch(self, branch: str) -> int | None: ...
    def merge_pr(self, pr: int, method: str = "squash") -> None: ...


class GitAdapter(Protocol):
    """Local git operations."""

    def setup_branch(self, branch_name: str, base: str) -> str: ...
    def sync_with_base(self, base: str) -> bool: ...
    def commit_artifacts(self, message: str, paths: list[str]) -> bool: ...
    def push(self) -> None: ...
    def read_state(self) -> str | None: ...
    def write_state(self, data: str) -> None: ...


class StageRunner(Protocol):
    """AI stage execution."""

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        is_resume: bool = False,
        on_progress: Callable[[str], None] | None = None,
        branch: str = "",
    ) -> RunResult: ...
