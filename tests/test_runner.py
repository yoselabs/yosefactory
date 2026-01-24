"""Tests for a2sdlc.runner — Claude CLI wrapper with session management."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.config import StageConfig
from a2sdlc.runner import (
    build_claude_cmd,
    get_session_id,
    get_session_path,
    parse_result,
    restore_session,
    run_claude,
    save_session,
)


# ── get_session_id ───────────────────────────────────────────────────


@pytest.mark.unit
class TestGetSessionId:
    def test_session_id_deterministic(self) -> None:
        sid1 = get_session_id("PROJ-42", "implement")
        sid2 = get_session_id("PROJ-42", "implement")
        assert sid1 == sid2

    def test_session_id_different_per_agent(self) -> None:
        sid_impl = get_session_id("PROJ-42", "implement")
        sid_review = get_session_id("PROJ-42", "review")
        assert sid_impl != sid_review

    def test_session_id_valid_uuid(self) -> None:
        sid = get_session_id("PROJ-42", "implement")
        parsed = uuid.UUID(sid)
        assert str(parsed) == sid
        assert parsed.version == 5


# ── get_session_path ─────────────────────────────────────────────────


@pytest.mark.unit
class TestGetSessionPath:
    def test_session_path_structure(self) -> None:
        sid = "abc-def-123"
        path = get_session_path(sid, "/home/user/project")
        expected = (
            Path.home()
            / ".claude"
            / "projects"
            / "home-user-project"
            / "abc-def-123.jsonl"
        )
        assert path == expected

    def test_session_path_strips_leading_slash(self) -> None:
        path = get_session_path("sid", "/foo/bar")
        assert "projects/foo-bar/" in str(path)


# ── build_claude_cmd ─────────────────────────────────────────────────


@pytest.mark.unit
class TestBuildClaudeCmd:
    @staticmethod
    def _config(**kw: Any) -> StageConfig:
        defaults: dict[str, Any] = {
            "name": "implement",
            "model": "claude-sonnet-4-6",
            "max_turns": 25,
            "allowed_tools": ["Bash", "Read"],
        }
        defaults.update(kw)
        return StageConfig(**defaults)

    def test_build_cmd_first_run(self) -> None:
        cfg = self._config()
        cmd = build_claude_cmd(
            "PROJ-1", "implement", cfg, "/tmp/sys.md", is_resume=False
        )
        assert "--session-id" in cmd
        assert "--resume" not in cmd

    def test_build_cmd_resume(self) -> None:
        cfg = self._config()
        cmd = build_claude_cmd(
            "PROJ-1", "implement", cfg, "/tmp/sys.md", is_resume=True
        )
        assert "--resume" in cmd
        assert "--session-id" not in cmd

    def test_build_cmd_includes_model(self) -> None:
        cfg = self._config(model="claude-opus-4")
        cmd = build_claude_cmd("PROJ-1", "implement", cfg, "/tmp/sys.md")
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-opus-4"

    def test_build_cmd_includes_tools(self) -> None:
        cfg = self._config(allowed_tools=["Bash", "Read", "Write"])
        cmd = build_claude_cmd("PROJ-1", "implement", cfg, "/tmp/sys.md")
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Bash,Read,Write"

    def test_build_cmd_includes_system_prompt_file(self) -> None:
        cfg = self._config()
        cmd = build_claude_cmd("PROJ-1", "implement", cfg, "/tmp/my-prompt.md")
        idx = cmd.index("--append-system-prompt-file")
        assert cmd[idx + 1] == "/tmp/my-prompt.md"


# ── parse_result ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestParseResult:
    def test_parse_result_success(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "All tests pass.",
                "session_id": "sid-123",
            }
        )
        parsed = parse_result(raw)
        assert parsed["success"] is True
        assert parsed["output"] == "All tests pass."
        assert parsed["error"] is None
        assert parsed["session_id"] == "sid-123"

    def test_parse_result_max_turns(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "subtype": "error_max_turns",
                "result": None,
                "session_id": "sid-456",
            }
        )
        parsed = parse_result(raw)
        assert parsed["success"] is False
        assert parsed["output"] == ""
        assert parsed["error"] == "max_turns"

    def test_parse_result_max_budget(self) -> None:
        raw = json.dumps(
            {
                "type": "result",
                "subtype": "error_max_budget_usd",
                "result": None,
                "session_id": "sid-789",
            }
        )
        parsed = parse_result(raw)
        assert parsed["success"] is False
        assert parsed["error"] == "budget"

    def test_parse_result_invalid_json(self) -> None:
        parsed = parse_result("not json at all {{{")
        assert parsed["success"] is False
        assert parsed["error"] == "json_parse"
        assert parsed["output"] == ""
        assert parsed["session_id"] == ""


# ── save_session / restore_session ───────────────────────────────────


@pytest.mark.unit
class TestSessionPersistence:
    def test_save_session_copies_file(self, tmp_path: Path) -> None:
        # Set up a fake Claude session file.
        cwd = str(tmp_path / "project")
        session_id = get_session_id("T-1", "impl")
        session_path = get_session_path(session_id, cwd)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text('{"line":1}\n')

        project_root = tmp_path / "project"
        project_root.mkdir(exist_ok=True)

        save_session("T-1", "impl", cwd, str(project_root))

        saved = (
            project_root
            / ".a2sdlc"
            / "sessions"
            / "T-1"
            / "impl"
            / f"{session_id}.jsonl"
        )
        assert saved.exists()
        assert saved.read_text() == '{"line":1}\n'

    def test_save_session_skips_missing(self, tmp_path: Path) -> None:
        # Should not raise when session file doesn't exist.
        save_session("T-1", "impl", "/nonexistent/path", str(tmp_path))

    def test_restore_session_returns_true(self, tmp_path: Path) -> None:
        cwd = str(tmp_path / "project")
        session_id = get_session_id("T-2", "review")

        # Create saved session in project.
        project_root = tmp_path / "project"
        saved_dir = project_root / ".a2sdlc" / "sessions" / "T-2" / "review"
        saved_dir.mkdir(parents=True)
        (saved_dir / f"{session_id}.jsonl").write_text('{"restored":true}\n')

        result = restore_session("T-2", "review", cwd, str(project_root))
        assert result is True

        # Verify it was copied to Claude's storage.
        claude_path = get_session_path(session_id, cwd)
        assert claude_path.exists()
        assert claude_path.read_text() == '{"restored":true}\n'

    def test_restore_session_returns_false(self, tmp_path: Path) -> None:
        result = restore_session("T-X", "agent", "/some/cwd", str(tmp_path))
        assert result is False


# ── run_claude ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestRunClaude:
    @patch("a2sdlc.runner.subprocess")
    @patch("a2sdlc.runner.restore_session", return_value=False)
    @patch("a2sdlc.runner.save_session")
    def test_run_claude_success(
        self,
        mock_save: MagicMock,
        mock_restore: MagicMock,
        mock_subprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "Done.",
                "session_id": "s1",
            }
        )
        mock_proc.returncode = 0
        mock_subprocess.run.return_value = mock_proc

        config = StageConfig(
            name="impl", model="claude-sonnet-4-6", max_turns=10, allowed_tools=["Bash"]
        )
        result = run_claude(
            user_prompt="Do the thing",
            system_prompt="You are helpful.",
            config=config,
            ticket_key="T-1",
            agent="impl",
            project_root=str(tmp_path),
        )

        assert result["success"] is True
        assert result["output"] == "Done."
        mock_subprocess.run.assert_called_once()
        mock_save.assert_called_once()

    @patch("a2sdlc.runner.subprocess")
    @patch("a2sdlc.runner.restore_session", return_value=True)
    @patch("a2sdlc.runner.save_session")
    def test_run_claude_resume(
        self,
        mock_save: MagicMock,
        mock_restore: MagicMock,
        mock_subprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "Resumed.",
                "session_id": "s2",
            }
        )
        mock_proc.returncode = 0
        mock_subprocess.run.return_value = mock_proc

        config = StageConfig(name="impl", max_turns=10, allowed_tools=["Bash"])
        result = run_claude(
            user_prompt="Continue",
            system_prompt="sys",
            config=config,
            ticket_key="T-2",
            agent="impl",
            project_root=str(tmp_path),
        )

        assert result["success"] is True
        # Verify resume flag was used in the command.
        call_args = mock_subprocess.run.call_args
        cmd = call_args[0][0]
        assert "--resume" in cmd

    @patch("a2sdlc.runner.subprocess")
    @patch("a2sdlc.runner.restore_session", return_value=False)
    @patch("a2sdlc.runner.save_session")
    def test_run_claude_timeout(
        self,
        mock_save: MagicMock,
        mock_restore: MagicMock,
        mock_subprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        import subprocess as real_subprocess

        mock_subprocess.run.side_effect = real_subprocess.TimeoutExpired(
            cmd="claude", timeout=60
        )
        mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired

        config = StageConfig(
            name="impl", max_turns=10, timeout_minutes=1, allowed_tools=["Bash"]
        )
        result = run_claude(
            user_prompt="slow task",
            system_prompt="sys",
            config=config,
            ticket_key="T-3",
            agent="impl",
            project_root=str(tmp_path),
        )

        assert result["success"] is False
        assert result["error"] == "timeout"
        mock_save.assert_called_once()
