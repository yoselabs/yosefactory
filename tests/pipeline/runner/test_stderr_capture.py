"""Runner stderr-capture surface — SDK ``ProcessError`` swallows the
subprocess stderr with the stub ``Check stderr output for details``;
the runner wires ``ClaudeAgentOptions.stderr`` so captured lines
appear in ``RunResult.error`` on failure paths.
"""

from __future__ import annotations

from typing import Callable, cast
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.config import StageConfig
from a2sdlc.domain.progress import ProgressState
from a2sdlc.pipeline.runner import run_stage


def _make_config() -> StageConfig:
    return StageConfig(
        name="spec",
        model="claude-sonnet-4-6",
        max_turns=5,
        timeout_minutes=1,
        allowed_tools=[],
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stderr_lines_surfaced_in_error() -> None:
    captured_options: dict[str, object] = {}

    def mock_options_cls(**kwargs: object) -> MagicMock:
        captured_options.update(kwargs)
        obj = MagicMock()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj

    async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
        cb = cast(Callable[[str], None], captured_options["stderr"])
        cb("session abc-123 already exists")
        cb("exiting with code 1")
        raise RuntimeError("Command failed with exit code 1")
        yield  # pragma: no cover

    with (
        patch("claude_agent_sdk.query", side_effect=mock_query),
        patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=mock_options_cls),
    ):
        result = await run_stage(
            user_prompt="x",
            system_prompt="y",
            config=_make_config(),
            ticket_key="PROJ-1",
            stage="spec",
            project_root="/tmp/test",
            progress_state=ProgressState(project_root="/tmp/test"),
        )

    assert callable(captured_options["stderr"])
    assert result.success is False
    assert result.error is not None
    assert "session abc-123 already exists" in result.error
    assert "exiting with code 1" in result.error
    assert "subprocess stderr" in result.error
