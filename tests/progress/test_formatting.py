"""Tests for progress comment rendering: format_progress, format_final, format_error."""

from __future__ import annotations

from typing import Any

import pytest

from a2sdlc.progress import (
    Milestone,
    ProgressState,
    ToolEntry,
    format_error,
    format_final,
    format_progress,
)
from a2sdlc.stats import StageRunStats


def _make_progress(**overrides: Any) -> ProgressState:
    return ProgressState(
        model=str(overrides.get("model", "claude-sonnet-4-6")),
        branch=str(overrides.get("branch", "feat/T-1")),
        max_turns=int(overrides.get("max_turns", 120)),
        context_window=int(overrides.get("context_window", 200_000)),
        project_root=str(overrides.get("project_root", "/tmp/test")),
        start_time=float(overrides.get("start_time", 1000.0)),
    )


def _make_stats(
    *,
    cost_usd: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    duration_ms: int = 0,
    num_turns: int = 0,
) -> StageRunStats:
    return StageRunStats(
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=duration_ms,
        num_turns=num_turns,
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
        assert "\u23f3 **a2sdlc:implement** in progress..." in text
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
        assert "\u23f3 **a2sdlc:spec** in progress..." in text


@pytest.mark.unit
class TestFormatFinal:
    def test_success(self) -> None:
        stats = _make_stats(
            tokens_in=312000,
            tokens_out=24000,
            cost_usd=2.14,
            duration_ms=522000,
            num_turns=45,
        )
        milestones = [
            Milestone(timestamp=42.0, label="brainstorming invoked"),
            Milestone(timestamp=390.0, label="requesting-code-review invoked"),
        ]
        text = format_final(
            "Done implementing.",
            stage="implement",
            stats=stats,
            milestones=milestones,
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "### \u2705 a2sdlc:implement" in text
        assert "Done implementing." in text
        assert "<details>" in text
        assert "312k" in text
        assert "$2.14" in text
        assert "\U0001f4cc 0:42 \u2014 brainstorming invoked" in text
        assert "\U0001f4cc 6:30 \u2014 requesting-code-review invoked" in text

    def test_tasks_in_details_block(self) -> None:
        stats = _make_stats(
            tokens_in=1000,
            tokens_out=500,
            cost_usd=0.10,
            duration_ms=10000,
            num_turns=5,
        )
        tasks = {
            "Write unit tests": "completed",
            "Implement feature": "completed",
            "Run linter": "in_progress",
            "Deploy": "pending",
        }
        text = format_final(
            "All done.",
            stage="implement",
            stats=stats,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
            tasks=tasks,
        )
        assert "<details>" in text
        assert "\u2705 Write unit tests" in text
        assert "\u2705 Implement feature" in text
        assert "\U0001f504 Run linter" in text
        assert "\u2b1c Deploy" in text

    def test_no_tasks_omits_section(self) -> None:
        stats = _make_stats(
            tokens_in=1000, tokens_out=500, cost_usd=0.05, duration_ms=30000
        )
        text = format_final(
            "Done.",
            stage="spec",
            stats=stats,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
            tasks=None,
        )
        assert "\u2b1c" not in text

    def test_no_milestones(self) -> None:
        stats = _make_stats(
            tokens_in=1000, tokens_out=500, cost_usd=0.05, duration_ms=30000
        )
        text = format_final(
            "Done.",
            stage="spec",
            stats=stats,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "### \u2705 a2sdlc:spec" in text
        assert "Done." in text
        assert "\U0001f4cc" not in text


@pytest.mark.unit
class TestHandoverMarkers:
    def test_format_final_includes_handover_marker(self) -> None:
        """format_final output must match HANDOVER_PATTERN for stage detection."""
        from a2sdlc.handover import HANDOVER_PATTERN

        stats = _make_stats(
            tokens_in=1000,
            tokens_out=500,
            cost_usd=0.05,
            duration_ms=30000,
            num_turns=5,
        )
        result = format_final(
            "Some output",
            stage="implement",
            stats=stats,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="agent/42",
            max_turns=25,
            context_window=200000,
        )
        assert HANDOVER_PATTERN.search(result) is not None
        assert "a2sdlc:implement" in result

    def test_format_error_includes_handover_marker(self) -> None:
        """format_error output must contain the a2sdlc: prefix for stage detection."""
        stats = _make_stats()
        result = format_error(
            "some error",
            stage="review",
            stats=stats,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="agent/42",
            max_turns=25,
            context_window=200000,
        )
        assert "a2sdlc:review" in result

    def test_format_progress_includes_handover_marker(self) -> None:
        """format_progress output must contain the a2sdlc: prefix."""
        ps = _make_progress()
        result = format_progress("spec", ps, elapsed=60.0)
        assert "a2sdlc:spec" in result


@pytest.mark.unit
class TestFormatError:
    def test_error_with_milestones(self) -> None:
        stats = _make_stats(
            tokens_in=100000,
            tokens_out=5000,
            cost_usd=0.50,
            duration_ms=3600000,
        )
        milestones = [Milestone(timestamp=42.0, label="brainstorming invoked")]
        text = format_error(
            "timeout (60min)",
            stage="implement",
            stats=stats,
            milestones=milestones,
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "\U0001f6a8" in text
        assert "**a2sdlc:implement** failed" in text
        assert "timeout (60min)" in text
        assert "claude-sonnet-4-6" in text
        assert "\U0001f4cc 0:42 \u2014 brainstorming invoked" in text

    def test_error_no_milestones(self) -> None:
        stats = _make_stats()
        text = format_error(
            "sdk_error",
            stage="spec",
            stats=stats,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=25,
            context_window=200_000,
        )
        assert "\U0001f6a8" in text
        assert "sdk_error" in text
        assert "\U0001f4cc" not in text
