"""StageRunner Protocol — contract for AI-stage execution adapters.

No in-tree impls: ``SdkStageRunner`` lives in ``pipeline/runner.py`` (it composes the
Claude Agent SDK and belongs to the pipeline layer, not adapters). This subfolder
exists solely to hold the Protocol and give the adapters/ layout kind-first
uniformity; future runner variants (fake, retrying, recording) would land here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from a2sdlc.config import StageConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult

if TYPE_CHECKING:
    from a2sdlc.domain.progress import ProgressState


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


__all__ = ["StageRunner"]
