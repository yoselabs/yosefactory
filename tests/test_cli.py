"""Tests for a2sdlc.cli — CLI entry point, orchestration, prompt assembly."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.cli import (
    _progress_update,
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
                "--run-id",
                "abc-123",
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
        assert args.run_id == "abc-123"
        assert args.model == "claude-opus-4"
        assert args.max_turns == 50
        assert args.supervised is True
        assert args.dry_run is True

    def test_parse_args_cleanup(self) -> None:
        args = parse_args(["cleanup", "--key", "PROJ-99"])
        assert args.command == "cleanup"
        assert args.key == "PROJ-99"

    def test_parse_args_progress_update(self) -> None:
        args = parse_args(["progress-update"])
        assert args.command == "progress-update"


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


# ── _progress_update ─────────────────────────────────────────────────


@pytest.mark.unit
class TestProgressUpdate:
    def test_progress_update_increments_counter(self, tmp_path: Path) -> None:
        env_file = tmp_path / "a2sdlc-env-PROJ-1.json"
        env_file.write_text(
            json.dumps(
                {
                    "comment_id": "c-123",
                    "ticket_key": "PROJ-1",
                    "stage": "implement",
                    "source": "github-issues",
                    "repo": "owner/repo",
                    "tickets_adapter": "github-issues",
                }
            )
        )

        with (
            patch("a2sdlc.cli.glob.glob", return_value=[str(env_file)]),
            patch("a2sdlc.cli.get_ticket_adapter") as mock_adapter_fn,
        ):
            with (
                patch("a2sdlc.cli._PROGRESS_DIR", str(tmp_path)),
                patch("a2sdlc.cli._ENV_DIR", str(tmp_path)),
            ):
                mock_adapter = MagicMock()
                mock_adapter_fn.return_value = mock_adapter

                _progress_update()

                # First call: counter=1, no update (only every 2)
                mock_adapter.update_comment.assert_not_called()

                _progress_update()

                # Second call: counter=2, should update
                mock_adapter.update_comment.assert_called_once()

    def test_progress_update_no_env_file(self) -> None:
        """Should not raise when no env file exists."""
        with patch("a2sdlc.cli.glob.glob", return_value=[]):
            _progress_update()  # Should not raise


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
            main(["run", "prd", "--source", "github-issues", "--key", "T-1"])
