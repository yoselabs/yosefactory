"""Tests for _handle_assistant_message — ProgressState mutation via async methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.evaluation.progress import ProgressState
from a2sdlc.pipeline.runner import _handle_assistant_message


def _make_progress() -> ProgressState:
    return ProgressState(project_root="/tmp/project")


@pytest.mark.unit
class TestHandleAssistantMessage:
    @pytest.mark.asyncio
    async def test_tool_entry_with_target(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, ToolUseBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=ToolUseBlock)
        block.name = "Read"
        block.input = {"file_path": "/tmp/project/src/app.py"}
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=1)

        assert len(progress.tool_log) == 1
        assert progress.tool_log[0].name == "Read"
        assert progress.tool_log[0].target == "src/app.py"

    @pytest.mark.asyncio
    async def test_skill_creates_milestone(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, ToolUseBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=ToolUseBlock)
        block.name = "Skill"
        block.input = {"skill": "brainstorming"}
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=1)

        assert len(progress.milestones) == 1
        assert progress.milestones[0].label == "brainstorming invoked"
        assert len(progress.tool_log) == 1

    @pytest.mark.asyncio
    async def test_usage_accumulation(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = {"input_tokens": 5000, "output_tokens": 1200}
        msg.total_cost_usd = None

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=1)

        assert progress.input_tokens == 5000
        assert progress.output_tokens == 1200

    @pytest.mark.asyncio
    async def test_usage_as_object(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        usage_obj = MagicMock()
        usage_obj.input_tokens = 8000
        usage_obj.output_tokens = 2000
        msg.usage = usage_obj
        msg.total_cost_usd = None

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=1)

        assert progress.input_tokens == 8000
        assert progress.output_tokens == 2000

    @pytest.mark.asyncio
    async def test_cost_updates_even_without_usage_block(self) -> None:
        """Cost from msg.total_cost_usd lands on progress_state regardless of
        whether the usage block is present, and a Metrics event is emitted on
        every assistant message so subscribers see live num_turns / elapsed
        even when this particular message had no token usage."""
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = 0.42

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=1)

        assert progress.total_cost_usd == 0.42
        assert progress.num_turns == 1

    @pytest.mark.asyncio
    async def test_no_usage(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=1)

        assert progress.input_tokens == 0
        assert progress.output_tokens == 0

    @pytest.mark.asyncio
    async def test_no_content(self) -> None:
        from claude_agent_sdk.types import AssistantMessage

        msg = MagicMock(spec=AssistantMessage)
        msg.content = None
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=1)

        assert len(progress.tool_log) == 0

    @pytest.mark.asyncio
    async def test_num_turns_set_in_metrics(self) -> None:
        """update_metrics receives the num_turns value passed in."""
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "working..."
        msg.content = [block]
        msg.usage = {"input_tokens": 100, "output_tokens": 50}
        msg.total_cost_usd = 0.01

        progress = _make_progress()
        await _handle_assistant_message(msg, progress, num_turns=3)

        assert progress.num_turns == 3
