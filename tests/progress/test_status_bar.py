"""Tests for progress status bar and primitive formatting helpers."""

from __future__ import annotations

import pytest

from a2sdlc.evaluation.progress import (
    Milestone,
    _format_duration,
    _format_milestones,
    _format_status_bar,
    _format_tokens,
)


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
        assert "22%" in bar
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
        assert "\u2014" in bar


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
