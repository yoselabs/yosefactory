"""Tests for a2sdlc.runner — SDK-based runner with streaming progress."""

from __future__ import annotations

import time

import pytest

from a2sdlc.config import get_session_id
from a2sdlc.runner import RunResult, format_cost, format_progress


# ── get_session_id (moved to config) ─────────────────────────────────


@pytest.mark.unit
class TestGetSessionId:
    def test_deterministic(self) -> None:
        sid1 = get_session_id("PROJ-42", "spec")
        sid2 = get_session_id("PROJ-42", "spec")
        assert sid1 == sid2

    def test_different_keys(self) -> None:
        sid1 = get_session_id("PROJ-1", "spec")
        sid2 = get_session_id("PROJ-2", "spec")
        assert sid1 != sid2

    def test_different_agents(self) -> None:
        sid1 = get_session_id("PROJ-1", "spec")
        sid2 = get_session_id("PROJ-1", "implement")
        assert sid1 != sid2


# ── format_cost ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatCost:
    def test_format_cost(self) -> None:
        result = RunResult(
            success=True,
            input_tokens=12450,
            output_tokens=3200,
            total_cost_usd=0.08,
            duration_ms=135000,
        )
        text = format_cost(result)
        assert "12,450 in" in text
        assert "3,200 out" in text
        assert "$0.08" in text
        assert "135s" in text

    def test_format_cost_zero(self) -> None:
        result = RunResult(success=False, error="timeout")
        text = format_cost(result)
        assert "$0.00" in text


# ── format_progress ──────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatProgress:
    def test_short_log(self) -> None:
        tools = ["Read", "Bash", "Write"]
        start = time.time() - 30
        text = format_progress("implement", tools, start)
        assert "implement" in text
        assert "- Read" in text
        assert "- Write" in text
        assert "Tools: 3" in text

    def test_long_log_shows_last_10(self) -> None:
        tools = [f"Tool-{i}" for i in range(25)]
        start = time.time() - 60
        text = format_progress("implement", tools, start)
        assert "... and 15 earlier actions" in text
        assert "Tool-24" in text
        assert "Tool-14" not in text
        assert "Tools: 25" in text

    def test_empty_log(self) -> None:
        text = format_progress("spec", [], time.time())
        assert "spec" in text
        assert "Tools: 0" in text


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
