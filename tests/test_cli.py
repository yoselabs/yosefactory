"""Tests for a2sdlc.cli — CLI entry point, orchestration, prompt assembly."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.cli import (
    assemble_system_prompt,
    find_project_root,
    main,
    parse_args,
    setup_logging,
)


# ── find_project_root ────────────────────────────────────────────────


@pytest.mark.unit
class TestFindProjectRoot:
    def test_find_project_root(self, tmp_path: Path) -> None:
        """Create temp dir with .a2sdlc/, verify found."""
        (tmp_path / ".a2sdlc").mkdir()
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)

        with patch("a2sdlc.cli.Path.cwd", return_value=subdir):
            result = find_project_root()

        assert result == tmp_path

    def test_find_project_root_not_found(self, tmp_path: Path) -> None:
        """Empty temp dir with no .a2sdlc/, verify returns cwd."""
        with patch("a2sdlc.cli.Path.cwd", return_value=tmp_path):
            result = find_project_root()

        assert result == tmp_path


# ── parse_args ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestParseArgs:
    def test_parse_args_run(self) -> None:
        args = parse_args(
            [
                "run",
                "implement",
                "--source",
                "github-issues",
                "--key",
                "PROJ-42",
                "--pr",
                "7",
                "--model",
                "claude-opus-4",
                "--max-turns",
                "50",
                "--supervised",
                "--dry-run",
            ]
        )
        assert args.command == "run"
        assert args.stage == "implement"
        assert args.source == "github-issues"
        assert args.key == "PROJ-42"
        assert args.pr == 7
        assert args.model == "claude-opus-4"
        assert args.max_turns == 50
        assert args.supervised is True
        assert args.dry_run is True

    def test_parse_args_cleanup(self) -> None:
        args = parse_args(["cleanup", "--key", "PROJ-99"])
        assert args.command == "cleanup"
        assert args.key == "PROJ-99"


# ── assemble_system_prompt ───────────────────────────────────────────


@pytest.mark.unit
class TestAssembleSystemPrompt:
    def test_assemble_system_prompt_with_files(self, tmp_path: Path) -> None:
        """Create temp prompts dir with files, verify concatenation order."""
        a2sdlc_dir = tmp_path / ".a2sdlc"
        prompts_dir = a2sdlc_dir / "prompts"
        prompts_dir.mkdir(parents=True)

        # system.md
        (prompts_dir / "system.md").write_text("SYSTEM PROMPT\n")

        # adapters
        adapters_dir = prompts_dir / "adapters"
        adapters_dir.mkdir()
        (adapters_dir / "b-adapter.md").write_text("ADAPTER B\n")
        (adapters_dir / "a-adapter.md").write_text("ADAPTER A\n")

        # stage
        stages_dir = prompts_dir / "stages"
        stages_dir.mkdir()
        (stages_dir / "implement.md").write_text("IMPLEMENT STAGE\n")

        result = assemble_system_prompt("implement", a2sdlc_dir)

        assert "SYSTEM PROMPT" in result
        assert "ADAPTER A" in result
        assert "ADAPTER B" in result
        assert "IMPLEMENT STAGE" in result
        # Adapters sorted: A before B
        assert result.index("ADAPTER A") < result.index("ADAPTER B")
        # System before adapters before stage
        assert result.index("SYSTEM PROMPT") < result.index("ADAPTER A")
        assert result.index("ADAPTER B") < result.index("IMPLEMENT STAGE")

    def test_assemble_system_prompt_empty(self, tmp_path: Path) -> None:
        """No prompt files exist, verify returns empty or near-empty string."""
        a2sdlc_dir = tmp_path / ".a2sdlc"
        a2sdlc_dir.mkdir()
        # No prompts dir at all, and mock importlib to also return nothing
        with patch("a2sdlc.cli.pkg_files") as mock_pkg:
            mock_pkg.return_value = tmp_path / "nonexistent-pkg"
            result = assemble_system_prompt("implement", a2sdlc_dir)

        assert result.strip() == ""


# ── setup_logging ────────────────────────────────────────────────────


@pytest.mark.unit
class TestSetupLogging:
    def test_setup_logging_creates_log_file(self, tmp_path: Path) -> None:
        setup_logging("PROJ-1", "implement", tmp_path)
        log_dir = tmp_path / ".a2sdlc" / "logs"
        assert log_dir.exists()
        log_files = list(log_dir.glob("PROJ-1-implement-*.log"))
        assert len(log_files) == 1


# ── main ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMain:
    def test_main_cleanup(self, tmp_path: Path) -> None:
        session_dir = tmp_path / ".a2sdlc" / "sessions" / "PROJ-1"
        session_dir.mkdir(parents=True)
        (session_dir / "data.jsonl").write_text("{}")

        with patch("a2sdlc.cli.find_project_root", return_value=tmp_path):
            main(["cleanup", "--key", "PROJ-1"])

        assert not session_dir.exists()

    def test_main_keyboard_interrupt(self) -> None:
        with (
            patch("a2sdlc.cli.parse_args") as mock_parse,
            patch("a2sdlc.cli.orchestrate", side_effect=KeyboardInterrupt),
            patch("a2sdlc.cli.find_project_root", return_value=Path("/tmp")),
        ):
            mock_parse.return_value = MagicMock(command="run")
            # Should not raise
            main(["run", "implement", "--source", "github-issues", "--key", "T-1"])
