"""Tests for _handle_assistant_message — ProgressState population."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.evaluation.progress import ProgressState
from a2sdlc.pipeline.runner import _handle_assistant_message


def _make_progress() -> ProgressState:
    return ProgressState(
        model="claude-sonnet-4-6",
        branch="feat/T-1",
        max_turns=120,
        context_window=200_000,
        project_root="/tmp/project",
        start_time=1000.0,
    )


@pytest.mark.unit
class TestHandleAssistantMessage:
    def test_tool_entry_with_target(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, ToolUseBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=ToolUseBlock)
        block.name = "Read"
        block.input = {"file_path": "/tmp/project/src/app.py"}
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        _handle_assistant_message(msg, progress, current_time=1001.5)

        assert len(progress.tool_log) == 1
        assert progress.tool_log[0].name == "Read"
        assert progress.tool_log[0].target == "src/app.py"
        assert progress.tool_log[0].timestamp == 1.5

    def test_skill_creates_milestone(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, ToolUseBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=ToolUseBlock)
        block.name = "Skill"
        block.input = {"skill": "brainstorming"}
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        _handle_assistant_message(msg, progress, current_time=1042.0)

        assert len(progress.milestones) == 1
        assert progress.milestones[0].label == "brainstorming invoked"
        assert progress.milestones[0].timestamp == 42.0
        assert len(progress.tool_log) == 1

    def test_usage_accumulation(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = {"input_tokens": 5000, "output_tokens": 1200}
        msg.total_cost_usd = None

        progress = _make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.input_tokens == 5000
        assert progress.output_tokens == 1200

    def test_usage_as_object(self) -> None:
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
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.input_tokens == 8000
        assert progress.output_tokens == 2000

    def test_cost_accumulation(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = 0.42

        progress = _make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.total_cost_usd == 0.42

    def test_no_usage(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.input_tokens == 0
        assert progress.output_tokens == 0

    def test_no_content(self) -> None:
        from claude_agent_sdk.types import AssistantMessage

        msg = MagicMock(spec=AssistantMessage)
        msg.content = None
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert len(progress.tool_log) == 0

    def test_progress_adapter_emits_tool_group(self) -> None:
        """When a progress_adapter is supplied, tool blocks emit on it
        (group_open / on_event / group_close) instead of printing ::group::.
        """
        from claude_agent_sdk.types import AssistantMessage, ToolUseBlock

        from tests.fakes import FakeProgressAdapter

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=ToolUseBlock)
        block.name = "Read"
        block.input = {"file_path": "/tmp/project/src/app.py"}
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = None

        progress = _make_progress()
        adapter = FakeProgressAdapter()
        _handle_assistant_message(
            msg, progress, current_time=1001.5, progress_adapter=adapter
        )

        assert adapter.groups_open == ["Tool: Read"]
        assert adapter.groups_closed == 1
        assert any(t == "tool_input" for t, _ in adapter.events)
