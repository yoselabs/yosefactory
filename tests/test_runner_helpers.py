"""Tests for runner helper functions: context window, formatting, path utils."""

from __future__ import annotations

import pytest

from a2sdlc.runner import (
    _extract_target,
    _format_duration,
    _format_tokens,
    _shorten_path,
    context_window_for_model,
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
