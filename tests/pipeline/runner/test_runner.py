"""Tests for a2sdlc.pipeline.runner — SDK-based runner with streaming progress."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.config import StageConfig
from a2sdlc.domain.progress import Milestone, ProgressState, ToolEntry
from a2sdlc.pipeline.runner import RunResult, run_stage


# ── ToolEntry ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestToolEntry:
    def test_create(self) -> None:
        entry = ToolEntry(timestamp=1.5, name="Read", target="src/app.py")
        assert entry.timestamp == 1.5
        assert entry.name == "Read"
        assert entry.target == "src/app.py"


# ── Milestone ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestMilestone:
    def test_create(self) -> None:
        ms = Milestone(timestamp=42.0, label="brainstorming invoked")
        assert ms.timestamp == 42.0
        assert ms.label == "brainstorming invoked"


# ── ProgressState ───────────────────────────────────────────────────


@pytest.mark.unit
class TestProgressState:
    def test_defaults(self) -> None:
        ps = ProgressState(project_root="/tmp/test")
        assert ps.input_tokens == 0
        assert ps.output_tokens == 0
        assert ps.total_cost_usd == 0.0
        assert ps.num_turns == 0
        assert ps.tool_log == []
        assert ps.milestones == []

    def test_accumulate(self) -> None:
        ps = ProgressState(project_root="/tmp/test")
        ps.tool_log.append(ToolEntry(timestamp=1.0, name="Read", target="f.py"))
        ps.milestones.append(Milestone(timestamp=2.0, label="skill invoked"))
        ps.input_tokens = 5000
        ps.num_turns = 3
        assert len(ps.tool_log) == 1
        assert len(ps.milestones) == 1
        assert ps.input_tokens == 5000


# NOTE: Format tests live in tests/progress/test_formatting.py


# ── RunResult ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRunResult:
    def test_default_values(self) -> None:
        r = RunResult(success=True)
        assert r.output == ""
        assert r.error is None
        assert r.total_cost_usd == 0.0
        assert r.tool_log == []

    def test_with_values(self) -> None:
        r = RunResult(
            success=True,
            output="Done",
            total_cost_usd=0.15,
            input_tokens=5000,
            output_tokens=2000,
            tool_log=["Read", "Write", "Bash"],
        )
        assert r.total_cost_usd == 0.15
        assert len(r.tool_log) == 3


# ── run_stage (async, mocked SDK) ─────────────────────────────────


def _make_config(**overrides: object) -> StageConfig:
    config = StageConfig(
        name="spec",
        model="claude-sonnet-4-6",
        max_turns=5,
        timeout_minutes=1,
        allowed_tools=[],
    )
    if overrides:
        config = config.model_copy(update=overrides)
    return config


def _make_progress(project_root: str = "/tmp/test") -> ProgressState:
    return ProgressState(project_root=project_root)


def _make_result_message(
    output: str = "Done",
    success: bool = True,
    cost: float = 0.05,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    duration_ms: int = 30000,
    num_turns: int = 3,
    session_id: str = "sess-123",
) -> MagicMock:
    """Build a mock ResultMessage."""
    from claude_agent_sdk.types import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.subtype = "success" if success else "error"
    msg.result = output
    msg.total_cost_usd = cost
    msg.duration_ms = duration_ms
    msg.num_turns = num_turns
    msg.session_id = session_id
    msg.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    return msg


def _make_assistant_message(tool_names: list[str] | None = None) -> MagicMock:
    """Build a mock AssistantMessage with optional tool use blocks."""
    from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

    msg = MagicMock(spec=AssistantMessage)
    msg.usage = None
    msg.total_cost_usd = None
    blocks = []
    if tool_names:
        for name in tool_names:
            block = MagicMock(spec=ToolUseBlock)
            block.name = name
            block.input = {}
            blocks.append(block)
    else:
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        blocks.append(block)
    msg.content = blocks
    return msg


@pytest.mark.unit
class TestRunStage:
    @pytest.mark.asyncio
    async def test_success_flow(self) -> None:
        assistant_msg = _make_assistant_message(["Read", "Write"])
        result_msg = _make_result_message(output="Spec done.")

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield assistant_msg
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions"),
        ):
            result = await run_stage(
                user_prompt="Build something",
                system_prompt="You are helpful",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
            )

        assert result.success is True
        assert result.output == "Spec done."
        assert result.total_cost_usd == 0.05
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        assert result.num_turns == 3
        assert result.tool_log == ["Read", "Write"]

    @pytest.mark.asyncio
    async def test_error_result(self) -> None:
        result_msg = _make_result_message(success=False, output="")

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions"),
        ):
            result = await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
            )

        assert result.success is False
        assert result.error == "error"

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            await asyncio.sleep(10)
            yield _make_result_message()  # pragma: no cover

        config = _make_config(timeout_minutes=0.001)  # ~60ms

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions"),
        ):
            result = await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=config,
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
            )

        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error

    @pytest.mark.asyncio
    async def test_sdk_exception(self) -> None:
        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            raise RuntimeError("SDK exploded")
            yield  # noqa: RET503  # make it an async generator

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions"),
        ):
            result = await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
            )

        assert result.success is False
        assert result.error is not None
        assert "RuntimeError" in result.error

    @pytest.mark.asyncio
    async def test_no_result_message(self) -> None:
        assistant_msg = _make_assistant_message()

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield assistant_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions"),
        ):
            result = await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
            )

        assert result.success is False
        assert result.error == "no_result"

    @pytest.mark.asyncio
    async def test_resume_session(self) -> None:
        result_msg = _make_result_message()
        options_obj = MagicMock()

        def mock_options_cls(**kwargs: object) -> MagicMock:
            for k, v in kwargs.items():
                setattr(options_obj, k, v)
            return options_obj

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=mock_options_cls),
        ):
            result = await run_stage(
                user_prompt="Continue",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
                is_resume=True,
            )

        assert result.success is True
        # Verify resume flag was set (not session_id).
        assert hasattr(options_obj, "resume")
        assert options_obj.resume is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("effort_in", "effort_sdk"),
        [
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "max"),
        ],
    )
    async def test_effort_forwarded_to_sdk(
        self, effort_in: str, effort_sdk: str
    ) -> None:
        """``effort`` kwarg is mapped and passed into ClaudeAgentOptions."""
        result_msg = _make_result_message()
        captured: dict[str, object] = {}

        def mock_options_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            obj = MagicMock()
            for k, v in kwargs.items():
                setattr(obj, k, v)
            return obj

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=mock_options_cls),
        ):
            result = await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
                effort=effort_in,
            )

        assert result.success is True
        assert captured.get("effort") == effort_sdk

    @pytest.mark.asyncio
    async def test_effort_none_not_passed_to_sdk(self) -> None:
        """When ``effort`` is None, it must not appear in ClaudeAgentOptions kwargs."""
        result_msg = _make_result_message()
        captured: dict[str, object] = {}

        def mock_options_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            obj = MagicMock()
            for k, v in kwargs.items():
                setattr(obj, k, v)
            return obj

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=mock_options_cls),
        ):
            await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
                effort=None,
            )

        assert "effort" not in captured

    @pytest.mark.asyncio
    async def test_usage_as_object(self) -> None:
        """Test usage extraction when SDK returns usage as an object, not dict."""
        from claude_agent_sdk.types import ResultMessage

        result_msg = MagicMock(spec=ResultMessage)
        result_msg.subtype = "success"
        result_msg.result = "Done"
        result_msg.total_cost_usd = 0.1
        result_msg.duration_ms = 5000
        result_msg.num_turns = 1
        result_msg.session_id = "s1"
        # Usage as an object (not dict).
        usage_obj = MagicMock()
        usage_obj.input_tokens = 2000
        usage_obj.output_tokens = 800
        result_msg.usage = usage_obj

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions"),
        ):
            result = await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=_make_progress(),
            )

        assert result.input_tokens == 2000
        assert result.output_tokens == 800

    @pytest.mark.asyncio
    async def test_progress_attached_to_result(self) -> None:
        assistant_msg = _make_assistant_message(["Read", "Write"])
        result_msg = _make_result_message(output="Done.")

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield assistant_msg
            yield result_msg

        progress = _make_progress()
        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions"),
        ):
            result = await run_stage(
                user_prompt="Build",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/test",
                progress_state=progress,
            )

        assert result.success is True
        assert result.progress is not None
        assert result.progress is progress
        assert len(result.progress.tool_log) == 2


# NOTE: TestHandleAssistantMessage lives in tests/runner/test_handler.py
# NOTE: Stderr-capture tests live in tests/pipeline/runner/test_stderr_capture.py
