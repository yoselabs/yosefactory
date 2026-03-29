"""Tests for runner helper functions: context window, formatting, path utils."""

from __future__ import annotations

from typing import Any

import pytest

from a2sdlc.runner import (
    Milestone,
    ProgressState,
    RunResult,
    ToolEntry,
    _extract_target,
    _format_duration,
    _format_milestones,
    _format_status_bar,
    _format_tokens,
    _shorten_path,
    context_window_for_model,
    format_error,
    format_final,
    format_progress,
)


# ── Context window ──────────────────────────────────────────────────


@pytest.mark.unit
class TestContextWindow:
    def test_known_model(self) -> None:
        assert context_window_for_model("claude-sonnet-4-6") == 200_000

    def test_known_opus(self) -> None:
        assert context_window_for_model("claude-opus-4-6") == 1_000_000

    def test_unknown_model_returns_none(self) -> None:
        assert context_window_for_model("gpt-4o") is None


# ── _shorten_path ───────────────────────────────────────────────────


@pytest.mark.unit
class TestShortenPath:
    def test_strips_project_root(self) -> None:
        assert _shorten_path("/tmp/project/src/app.py", "/tmp/project") == "src/app.py"

    def test_no_common_prefix(self) -> None:
        assert (
            _shorten_path("/other/path/file.py", "/tmp/project")
            == "/other/path/file.py"
        )

    def test_empty_path(self) -> None:
        assert _shorten_path("", "/tmp/project") == ""

    def test_glob_pattern(self) -> None:
        assert _shorten_path("**/*.py", "/tmp/project") == "**/*.py"


# ── _extract_target ─────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractTarget:
    def test_read(self) -> None:
        result = _extract_target("Read", {"file_path": "/tmp/p/src/app.py"}, "/tmp/p")
        assert result == "src/app.py"

    def test_edit(self) -> None:
        result = _extract_target("Edit", {"file_path": "/tmp/p/src/app.py"}, "/tmp/p")
        assert result == "src/app.py"

    def test_bash(self) -> None:
        result = _extract_target("Bash", {"command": "pytest tests/ -v"}, "/tmp/p")
        assert result == "`pytest tests/ -v`"

    def test_bash_truncates(self) -> None:
        long_cmd = "x" * 100
        result = _extract_target("Bash", {"command": long_cmd}, "/tmp/p")
        assert result == f"`{'x' * 60}`"

    def test_grep(self) -> None:
        result = _extract_target("Grep", {"pattern": "handle_event"}, "/tmp/p")
        assert result == "handle_event"

    def test_glob(self) -> None:
        result = _extract_target("Glob", {"pattern": "**/*.py"}, "/tmp/p")
        assert result == "**/*.py"

    def test_write(self) -> None:
        result = _extract_target("Write", {"file_path": "/tmp/p/new.py"}, "/tmp/p")
        assert result == "new.py"

    def test_skill(self) -> None:
        result = _extract_target("Skill", {"skill": "brainstorming"}, "/tmp/p")
        assert result == "brainstorming"

    def test_unknown_tool(self) -> None:
        result = _extract_target("CustomTool", {"arg": "val"}, "/tmp/p")
        assert result == ""

    def test_empty_input(self) -> None:
        result = _extract_target("Read", {}, "/tmp/p")
        assert result == ""


# ── _format_duration ────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatDuration:
    def test_seconds(self) -> None:
        assert _format_duration(45.0) == "45s"

    def test_minutes_seconds(self) -> None:
        assert _format_duration(135.0) == "2m 15s"

    def test_hours_minutes(self) -> None:
        assert _format_duration(3720.0) == "1h 2m"

    def test_zero(self) -> None:
        assert _format_duration(0.0) == "0s"


# ── _format_tokens ──────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatTokens:
    def test_thousands(self) -> None:
        assert _format_tokens(45000) == "45k"

    def test_hundreds_of_thousands(self) -> None:
        assert _format_tokens(312000) == "312k"

    def test_small(self) -> None:
        assert _format_tokens(500) == "1k"

    def test_zero(self) -> None:
        assert _format_tokens(0) == "0k"


# ── _format_status_bar ─────────────────────────────────────────────


@pytest.mark.unit
class TestFormatStatusBar:
    def test_full_bar(self) -> None:
        bar = _format_status_bar(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            input_tokens=45000,
            output_tokens=12000,
            total_cost_usd=0.72,
            duration_seconds=135.0,
            num_turns=12,
            max_turns=120,
            context_window=200_000,
        )
        assert "claude-sonnet-4-6" in bar
        assert "feat/T-1" in bar
        assert "45k/200k" in bar
        assert "22%" in bar  # 45000/200000 = 22.5%, int() truncates
        assert "$0.72" in bar
        assert "45k in" in bar
        assert "12k out" in bar
        assert "2m 15s" in bar
        assert "12/120" in bar
        assert bar.startswith("| Model")
        assert "|-------|" in bar

    def test_unknown_context_window(self) -> None:
        bar = _format_status_bar(
            model="custom-model",
            branch="main",
            input_tokens=5000,
            output_tokens=1000,
            total_cost_usd=0.01,
            duration_seconds=10.0,
            num_turns=2,
            max_turns=25,
            context_window=None,
        )
        assert "custom-model" in bar
        assert "5k" in bar
        assert "%" not in bar

    def test_unknown_tokens(self) -> None:
        bar = _format_status_bar(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            input_tokens=0,
            output_tokens=0,
            total_cost_usd=0.0,
            duration_seconds=30.0,
            num_turns=5,
            max_turns=120,
            context_window=200_000,
        )
        assert "\u2014" in bar  # em dash for unknown values


# ── _format_milestones ─────────────────────────────────────────────


@pytest.mark.unit
class TestFormatMilestones:
    def test_empty(self) -> None:
        assert _format_milestones([]) == ""

    def test_single(self) -> None:
        ms = [Milestone(timestamp=42.0, label="brainstorming invoked")]
        text = _format_milestones(ms)
        assert "\U0001f4cc" in text
        assert "0:42" in text
        assert "brainstorming invoked" in text

    def test_multiple(self) -> None:
        ms = [
            Milestone(timestamp=42.0, label="brainstorming invoked"),
            Milestone(timestamp=135.0, label="writing-plans invoked"),
        ]
        text = _format_milestones(ms)
        assert text.count("\U0001f4cc") == 2
        assert "0:42" in text
        assert "2:15" in text


# ── format_progress ────────────────────────────────────────────────


def _make_progress(**overrides: Any) -> ProgressState:
    return ProgressState(
        model=str(overrides.get("model", "claude-sonnet-4-6")),
        branch=str(overrides.get("branch", "feat/T-1")),
        max_turns=int(overrides.get("max_turns", 120)),
        context_window=int(overrides.get("context_window", 200_000)),
        project_root=str(overrides.get("project_root", "/tmp/test")),
        start_time=float(overrides.get("start_time", 1000.0)),
    )


@pytest.mark.unit
class TestFormatProgress:
    def test_basic_progress(self) -> None:
        ps = _make_progress()
        ps.input_tokens = 45000
        ps.output_tokens = 12000
        ps.total_cost_usd = 0.72
        ps.num_turns = 12
        ps.tool_log = [
            ToolEntry(timestamp=1.0, name="Read", target="src/app.py"),
            ToolEntry(timestamp=2.0, name="Edit", target="src/app.py"),
        ]
        text = format_progress("implement", ps, elapsed=135.0)
        assert "\u23f3 **implement** in progress..." in text
        assert "claude-sonnet-4-6" in text
        assert "feat/T-1" in text
        assert "| Read | src/app.py |" in text
        assert "| Edit | src/app.py |" in text

    def test_tool_log_truncation(self) -> None:
        ps = _make_progress()
        ps.tool_log = [
            ToolEntry(timestamp=float(i), name=f"Tool-{i}", target=f"f{i}.py")
            for i in range(25)
        ]
        text = format_progress("implement", ps, elapsed=60.0)
        assert "*(15 earlier)*" in text
        assert "Tool-24" in text
        assert "Tool-14" not in text

    def test_milestones_shown(self) -> None:
        ps = _make_progress()
        ps.milestones = [Milestone(timestamp=42.0, label="brainstorming invoked")]
        text = format_progress("spec", ps, elapsed=60.0)
        assert "\U0001f4cc 0:42 \u2014 brainstorming invoked" in text

    def test_empty_log(self) -> None:
        ps = _make_progress()
        text = format_progress("spec", ps, elapsed=0.0)
        assert "\u23f3 **spec** in progress..." in text


# ── format_final ───────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatFinal:
    def test_success(self) -> None:
        result = RunResult(
            success=True,
            output="Done implementing.",
            input_tokens=312000,
            output_tokens=24000,
            total_cost_usd=2.14,
            duration_ms=522000,
            num_turns=45,
        )
        milestones = [
            Milestone(timestamp=42.0, label="brainstorming invoked"),
            Milestone(timestamp=390.0, label="requesting-code-review invoked"),
        ]
        text = format_final(
            result,
            milestones=milestones,
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "Done implementing." in text
        assert "---" in text
        assert "312k" in text
        assert "$2.14" in text
        assert "\U0001f4cc 0:42 \u2014 brainstorming invoked" in text
        assert "\U0001f4cc 6:30 \u2014 requesting-code-review invoked" in text

    def test_no_milestones(self) -> None:
        result = RunResult(
            success=True,
            output="Done.",
            input_tokens=1000,
            output_tokens=500,
            total_cost_usd=0.05,
            duration_ms=30000,
        )
        text = format_final(
            result,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "Done." in text
        assert "\U0001f4cc" not in text


# ── format_error ───────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatError:
    def test_error_with_milestones(self) -> None:
        result = RunResult(
            success=False,
            error="timeout (60min)",
            input_tokens=100000,
            output_tokens=5000,
            total_cost_usd=0.50,
            duration_ms=3600000,
        )
        milestones = [Milestone(timestamp=42.0, label="brainstorming invoked")]
        text = format_error(
            result,
            stage="implement",
            milestones=milestones,
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "\U0001f6a8" in text
        assert "**implement** failed" in text
        assert "timeout (60min)" in text
        assert "claude-sonnet-4-6" in text
        assert "\U0001f4cc 0:42 \u2014 brainstorming invoked" in text

    def test_error_no_milestones(self) -> None:
        result = RunResult(success=False, error="sdk_error")
        text = format_error(
            result,
            stage="spec",
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=25,
            context_window=200_000,
        )
        assert "\U0001f6a8" in text
        assert "sdk_error" in text
        assert "\U0001f4cc" not in text
