"""Adapter protocols — platform-agnostic interfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from a2sdlc.config import StageConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult

if TYPE_CHECKING:
    from a2sdlc.evaluation.progress import ProgressEvent, ProgressState


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
        progress_state: "ProgressState",
        is_resume: bool = False,
        branch: str = "",
    ) -> RunResult: ...


class Subscriber(Protocol):
    """Receives ``ProgressEvent`` instances from ``ProgressState``.

    Implementations filter by ``isinstance`` and ignore event types they
    don't care about. ``handle`` is async because the runner is already
    async; sync subscribers just don't ``await`` anything inside.
    """

    async def handle(self, event: "ProgressEvent") -> None: ...
