"""Adapter protocols — platform-agnostic interfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from a2sdlc.config import StageConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult


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


class ProgressAdapter(Protocol):
    """Render live progress events from the pipeline."""

    def on_stage_start(self, stage: StageName, session_id: str) -> None: ...
    def on_event(self, event_type: str, text: str) -> None: ...
    def on_stage_end(self, stage: StageName, success: bool) -> None: ...
    def on_group_open(self, title: str) -> None: ...
    def on_group_close(self) -> None: ...
