"""Tests for a2sdlc.cli — CLI entry point, prompt assembly, project root."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.cli.dispatch import (
    find_project_root,
    setup_logging,
)
from a2sdlc.cli.main import main
from a2sdlc.assembly.prompt import assemble_system_prompt


# ── find_project_root ────────────────────────────────────────────────


@pytest.mark.unit
class TestFindProjectRoot:
    def test_find_project_root(self, tmp_path: Path) -> None:
        """Create temp dir with .a2sdlc/, verify found."""
        (tmp_path / ".a2sdlc").mkdir()
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)

        with patch("a2sdlc.cli.dispatch.Path.cwd", return_value=subdir):
            result = find_project_root()

        assert result == tmp_path

    def test_find_project_root_not_found(self, tmp_path: Path) -> None:
        """Empty temp dir with no .a2sdlc/, verify returns cwd."""
        with patch("a2sdlc.cli.dispatch.Path.cwd", return_value=tmp_path):
            result = find_project_root()

        assert result == tmp_path


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
        with patch("a2sdlc.assembly.prompt.pkg_files") as mock_pkg:
            mock_pkg.return_value = tmp_path / "nonexistent-pkg"
            result = assemble_system_prompt("implement", a2sdlc_dir)

        assert result.strip() == ""

    def test_implement_stage_contains_skill_scoping(self, tmp_path: Path) -> None:
        """Implement stage prompt must tell agent not to invoke brainstorming."""
        a2sdlc_dir = tmp_path / ".a2sdlc"
        a2sdlc_dir.mkdir()
        # Use empty project dir so function falls back to package-bundled prompts.
        result = assemble_system_prompt("implement", a2sdlc_dir)

        result_lower = result.lower()
        assert "do not" in result_lower, "implement prompt missing 'DO NOT' directive"
        assert "brainstorming" in result_lower, (
            "implement prompt missing 'brainstorming' keyword"
        )

    def test_review_stage_contains_skill_scoping(self, tmp_path: Path) -> None:
        """Review stage prompt must tell agent not to invoke brainstorming."""
        a2sdlc_dir = tmp_path / ".a2sdlc"
        a2sdlc_dir.mkdir()
        result = assemble_system_prompt("review", a2sdlc_dir)

        result_lower = result.lower()
        assert "do not" in result_lower, "review prompt missing 'DO NOT' directive"
        assert "brainstorming" in result_lower, (
            "review prompt missing 'brainstorming' keyword"
        )

    def test_spec_stage_does_not_restrict_brainstorming(self, tmp_path: Path) -> None:
        """Spec stage should NOT tell the agent to skip brainstorming."""
        a2sdlc_dir = tmp_path / ".a2sdlc"
        a2sdlc_dir.mkdir()
        result = assemble_system_prompt("spec", a2sdlc_dir)

        # spec.md should reference brainstorming as something to USE, not avoid
        result_lower = result.lower()
        assert "brainstorming" in result_lower, (
            "spec prompt should mention brainstorming skill"
        )
        # Ensure the spec prompt doesn't accidentally include a DO NOT brainstorming directive
        # (a simple heuristic: "do not" and "brainstorming" should not appear on the same line)
        for line in result.splitlines():
            line_lower = line.lower()
            if "brainstorming" in line_lower:
                assert "do not" not in line_lower, (
                    f"spec prompt line unexpectedly restricts brainstorming: {line!r}"
                )


# ── setup_logging ────────────────────────────────────────────────────


@pytest.mark.unit
class TestSetupLogging:
    def test_setup_logging_creates_log_file(self, tmp_path: Path) -> None:
        setup_logging("PROJ-1", "implement", tmp_path)
        log_dir = tmp_path / ".a2sdlc" / "logs"
        assert log_dir.exists()
        log_files = list(log_dir.glob("PROJ-1-implement-*.log"))
        assert len(log_files) == 1

    def test_setup_logging_preserves_extra_fields(self, tmp_path: Path) -> None:
        """`extra={...}` kwargs on logger calls must appear in JSON output."""
        import json
        import logging

        # Reset root handlers so assertions see only this test's output.
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)

        setup_logging("PROJ-1", "implement", tmp_path)
        logging.getLogger("a2sdlc.test").info(
            "dispatch.route",
            extra={"target_stage": "implement", "is_feedback": True},
        )
        for h in root.handlers:
            h.flush()

        log_file = next((tmp_path / ".a2sdlc" / "logs").glob("PROJ-1-implement-*.log"))
        lines = [
            json.loads(ln) for ln in log_file.read_text().splitlines() if ln.strip()
        ]
        route = next(ln for ln in lines if ln["msg"] == "dispatch.route")
        assert route["target_stage"] == "implement"
        assert route["is_feedback"] is True
        assert route["level"] == "INFO"


# ── main ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMainRunStage:
    def test_main_routes_run_stage_to_impl(self, tmp_path: Path) -> None:
        """``a2sdlc run-stage ...`` delegates to the run_stage subcommand."""
        with patch("a2sdlc.cli.run_stage._run_stage_impl", return_value=0) as mock_impl:
            with pytest.raises(SystemExit) as exc:
                main(["run-stage", "spec", str(tmp_path)])

        assert exc.value.code == 0
        mock_impl.assert_called_once()
        assert mock_impl.call_args.kwargs["stage"].value == "spec"
        assert mock_impl.call_args.kwargs["project_root"] == tmp_path.resolve()


@pytest.mark.unit
class TestMainDispatch:
    def test_main_dispatch_constructs_github_adapters(self, tmp_path: Path) -> None:
        """main() with 'dispatch' wires GitHub adapters via env-derived token/repo."""
        (tmp_path / ".a2sdlc").mkdir()
        (tmp_path / ".a2sdlc" / "config.yaml").write_text("default_base: main\n")

        dispatch_result = MagicMock(blocked=False, error=None)

        with (
            patch("github.Github") as mock_github,
            # NOTE: these three patch() calls target the package namespace where cli.py looks up the names (via `from a2sdlc.adapters.<kind> import X`), not the submodule where they're defined. patch()ing the submodule attribute would miss the binding cli.py uses and the tests would silently pass with mock_call_count == 0.
            patch("a2sdlc.adapters.work.GitHubWorkAdapter") as mock_work,
            patch("a2sdlc.adapters.review.GitHubReviewAdapter") as mock_review,
            patch("a2sdlc.adapters.git.LocalGitAdapter") as mock_git,
            patch("a2sdlc.pipeline.dispatch.dispatch") as mock_dispatch,
            patch.dict(
                "os.environ",
                {"GITHUB_TOKEN": "tkn", "GITHUB_REPOSITORY": "o/r"},
                clear=False,
            ),
        ):
            mock_git.return_value = MagicMock(name="git")
            mock_repo = MagicMock(name="repo")
            mock_github.return_value.get_repo.return_value = mock_repo

            async def _fake_dispatch(_ctx: object) -> object:
                return dispatch_result

            mock_dispatch.side_effect = _fake_dispatch

            with pytest.raises(SystemExit) as exc:
                main(["dispatch", "--project-root", str(tmp_path)])
            assert exc.value.code == 0

        # Github(token).get_repo(repo_name) called with env-derived values;
        # GitHubWorkAdapter called with just the repo (no trigger_mention override).
        mock_github.assert_called_once_with("tkn")
        mock_github.return_value.get_repo.assert_called_once_with("o/r")
        assert mock_work.call_count == 1
        assert "trigger_mention" not in mock_work.call_args.kwargs
        mock_review.assert_called_once()

    def test_main_dispatch_dispatcher_mode(self, tmp_path: Path) -> None:
        """When DISPATCHER_URL is set, use WorkflowInputReader + DispatcherEventSubscriber."""
        (tmp_path / ".a2sdlc").mkdir()
        (tmp_path / ".a2sdlc" / "config.yaml").write_text("default_base: main\n")

        dispatch_result = MagicMock(blocked=False, error=None)

        with (
            patch("github.Github") as mock_github,
            patch("a2sdlc.adapters.review.GitHubReviewAdapter") as mock_review,
            patch("a2sdlc.adapters.git.LocalGitAdapter") as mock_git,
            patch(
                "a2sdlc.adapters.work.workflow_input.WorkflowInputReader"
            ) as mock_work,
            patch(
                "a2sdlc.adapters.subscriber.dispatcher_event.DispatcherEventSubscriber"
            ) as mock_dispatcher_sub,
            patch("a2sdlc.adapters.subscriber.console.ConsoleSubscriber"),
            patch("httpx.Client") as mock_httpx,
            patch("a2sdlc.pipeline.dispatch.dispatch") as mock_dispatch,
            patch.dict(
                "os.environ",
                {
                    "DISPATCHER_URL": "http://dispatcher.example.com",
                    "GITHUB_TOKEN": "tkn",
                    "GITHUB_REPOSITORY": "o/r",
                    "RUN_ID": "run-123",
                    "RUN_HMAC": "hmac-abc",
                },
                clear=False,
            ),
        ):
            mock_git.return_value = MagicMock(name="git")
            mock_repo = MagicMock(name="repo")
            mock_github.return_value.get_repo.return_value = mock_repo

            async def _fake_dispatch(_ctx: object) -> object:
                return dispatch_result

            mock_dispatch.side_effect = _fake_dispatch

            with pytest.raises(SystemExit) as exc:
                main(["dispatch", "--project-root", str(tmp_path)])
            assert exc.value.code == 0

        # Dispatcher mode: WorkflowInputReader is the work adapter, not GitHubWorkAdapter.
        assert mock_work.call_count == 1
        mock_review.assert_called_once()
        # DispatcherEventSubscriber is constructed with env-derived values.
        mock_dispatcher_sub.assert_called_once_with(
            dispatcher_url="http://dispatcher.example.com",
            run_id="run-123",
            run_hmac="hmac-abc",
            http=mock_httpx.return_value,
        )
