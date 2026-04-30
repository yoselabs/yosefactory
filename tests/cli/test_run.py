"""``a2sdlc run`` CLI prelude — exit-code contract.

Spec §CLI surface steps 1-6 + §Failure modes table. Each test spawns
the CLI as a subprocess so we exercise real argparse / typer wiring
and OS-level exit codes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from a2sdlc.cli import run as run_module
from a2sdlc.cli.main import app


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    full_env = {**os.environ, **(env or {})}
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=full_env,
    )


def _init_repo(repo: Path, base: str = "feature/x") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@e",
    }
    _git(repo, "init", "-q", "-b", base, env=env)
    (repo / ".a2sdlc").mkdir(exist_ok=True)
    (repo / ".a2sdlc" / "config.yaml").write_text(
        textwrap.dedent(
            """\
            mode: local
            adapters:
              work: local-file
              review: local
            subscribers:
              - console
            required_env:
              - ANTHROPIC_API_KEY
            pipeline:
              max_review_cycles: 3
              protected_bases:
                - main
                - master
            """
        )
    )
    (repo / "INPUT.md").write_text("add greet() function\n")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "init", env=env)


def _run_cli(
    repo: Path,
    *args: str,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m a2sdlc run`` from ``repo`` as cwd."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY",)}
    # Default: provide a fake key so env step passes unless caller drops it.
    env.setdefault("ANTHROPIC_API_KEY", "sk-test-fake")
    if env_overrides:
        for k, v in env_overrides.items():
            if v is None:  # type: ignore[comparison-overlap]
                env.pop(k, None)
            else:
                env[k] = v
    return subprocess.run(
        [sys.executable, "-m", "a2sdlc", "run", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.unit
class TestRunPrelude:
    def test_missing_required_env_exits_2(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        result = _run_cli(repo, env_overrides={"ANTHROPIC_API_KEY": ""})
        assert result.returncode == 2, result.stderr
        assert "ANTHROPIC_API_KEY" in result.stderr
        assert "required environment variables" in result.stderr

    def test_protected_base_exits_4(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="main")
        result = _run_cli(repo)
        assert result.returncode == 4, result.stderr
        assert "protected base" in result.stderr
        assert "'main'" in result.stderr

    def test_dirty_tree_exits_5(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="feature/x")
        # Modify a tracked file.
        (repo / "INPUT.md").write_text("dirty edit\n")
        result = _run_cli(repo)
        assert result.returncode == 5, result.stderr
        assert "uncommitted changes" in result.stderr

    def test_run_branch_exists_exits_7(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="feature/x")

        # Force the run-branch generator to produce a name that
        # already exists, then assert the duplicate-branch guard fires.
        runner = CliRunner()
        env = {**os.environ, "ANTHROPIC_API_KEY": "sk-test"}
        # Pre-create a branch matching the format we expect.
        existing = "a2sdlc/auto/feature-x/20260101-000000-deadbe"
        subprocess.run(
            ["git", "branch", existing],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        monkeypatch.setattr(
            run_module,
            "format_run_branch",
            lambda *_a, **_k: existing,
        )
        monkeypatch.chdir(repo)

        result = runner.invoke(app, ["run"], env=env)
        assert result.exit_code == 7
        assert "already exists" in result.stderr

    def test_input_md_missing_on_base_exits_6(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@e",
        }
        _git(repo, "init", "-q", "-b", "feature/x", env=env)
        (repo / ".a2sdlc").mkdir()
        (repo / ".a2sdlc" / "config.yaml").write_text(
            textwrap.dedent(
                """\
                mode: local
                adapters:
                  work: local-file
                  review: local
                subscribers:
                  - console
                required_env:
                  - ANTHROPIC_API_KEY
                """
            )
        )
        # Commit something that is NOT INPUT.md.
        (repo / "README").write_text("no input here\n")
        _git(repo, "add", "-A", env=env)
        _git(repo, "commit", "-q", "-m", "init", env=env)
        result = _run_cli(repo)
        assert result.returncode == 6, result.stderr
        assert "INPUT.md not found" in result.stderr


@pytest.mark.unit
class TestRunHelpers:
    """Direct unit coverage for cli.run internals (subprocess-based
    end-to-end tests don't surface their lines under coverage)."""

    def test_required_env_aggregates_engine_and_adapters(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        from a2sdlc.config_run import load_run_config

        cfg = load_run_config(repo / ".a2sdlc" / "config.yaml")
        reqs = run_module._required_env_for(cfg)
        # engine source must include ANTHROPIC_API_KEY; local adapter has none.
        sources = {src for src, _ in reqs}
        assert "engine" in sources
        names = [n for _, names in reqs for n in names]
        assert "ANTHROPIC_API_KEY" in names

    def test_required_env_includes_github_adapter(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        cfg_path = repo / ".a2sdlc" / "config.yaml"
        cfg_path.write_text(
            textwrap.dedent(
                """\
                mode: github
                adapters:
                  work: github
                  review: github
                required_env: []
                """
            )
        )
        from a2sdlc.config_run import load_run_config

        cfg = load_run_config(cfg_path)
        reqs = run_module._required_env_for(cfg)
        names = [n for _, names in reqs for n in names]
        assert "GITHUB_TOKEN" in names

    def test_resolve_base_reads_head(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="feature/y")
        assert run_module._resolve_base(None, repo) == "feature/y"
        assert run_module._resolve_base("override/branch", repo) == "override/branch"

    def test_read_input_md_returns_committed_bytes(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="feature/x")
        # The working tree is allowed to drift; we read base HEAD only.
        (repo / "INPUT.md").write_text("local edits should be ignored\n")
        out = run_module._read_input_md("feature/x", repo)
        assert out == b"add greet() function\n"

    def test_read_input_md_missing_raises(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="feature/x")
        # Remove INPUT.md from base HEAD by creating a new branch without it.
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e",
        }
        _git(repo, "rm", "INPUT.md", env=env)
        _git(repo, "commit", "-m", "drop input", env=env)
        with pytest.raises(FileNotFoundError):
            run_module._read_input_md("feature/x", repo)

    def test_branch_exists_local_and_missing(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="feature/x")
        assert run_module._branch_exists("feature/x", repo) is True
        assert run_module._branch_exists("does/not/exist", repo) is False

    def test_invalid_config_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / ".a2sdlc" / "config.yaml").write_text("not: [valid yaml\n")
        runner = CliRunner()
        monkeypatch.chdir(repo)
        result = runner.invoke(
            app, ["run"], env={**os.environ, "ANTHROPIC_API_KEY": "sk"}
        )
        assert result.exit_code == 1
        assert "error:" in result.stderr

    def test_lockfile_busy_exits_3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        def _busy(*_a, **_k):
            from a2sdlc.runtime.lockfile import LockfileBusy

            raise LockfileBusy("another a2sdlc run is in progress")

        monkeypatch.setattr(run_module, "acquire_lock", _busy)
        monkeypatch.chdir(repo)
        runner = CliRunner()
        result = runner.invoke(
            app, ["run"], env={**os.environ, "ANTHROPIC_API_KEY": "sk"}
        )
        assert result.exit_code == 3
        assert "another a2sdlc run" in result.stderr

    def test_allow_protected_base_passes_step3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="main")
        # Stub the pipeline driver so we don't run a real workflow.
        called = {}

        def _fake_drive(**kw):
            called.update(kw)
            sys_stdout_write = sys.stdout.write
            sys_stdout_write(f"done.\nbranch: {kw['run_branch']}\n")

        monkeypatch.setattr("a2sdlc.cli.run_pipeline.drive_pipeline", _fake_drive)
        monkeypatch.chdir(repo)
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["run", "--allow-protected-base"],
            env={**os.environ, "ANTHROPIC_API_KEY": "sk"},
        )
        assert result.exit_code == 0, result.stderr
        assert called["base"] == "main"
        assert called["run_branch"].startswith("a2sdlc/auto/main/")

    def test_mode_override_applies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        called = {}

        def _fake_drive(**kw):
            called["mode"] = kw["config"].mode

        monkeypatch.setattr("a2sdlc.cli.run_pipeline.drive_pipeline", _fake_drive)
        monkeypatch.chdir(repo)
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["run", "--mode", "github"],
            env={
                **os.environ,
                "ANTHROPIC_API_KEY": "sk",
                "GITHUB_TOKEN": "ghp_x",
            },
        )
        assert result.exit_code == 0, result.stderr
        assert called["mode"] == "github"

    def test_in_process_missing_env_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        monkeypatch.chdir(repo)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        runner = CliRunner()
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 2
        assert "ANTHROPIC_API_KEY" in result.stderr

    def test_in_process_protected_base_exits_4(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="main")
        monkeypatch.chdir(repo)
        runner = CliRunner()
        result = runner.invoke(
            app, ["run"], env={**os.environ, "ANTHROPIC_API_KEY": "sk"}
        )
        assert result.exit_code == 4

    def test_in_process_dirty_tree_exits_5(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo, base="feature/x")
        (repo / "INPUT.md").write_text("dirty\n")
        monkeypatch.chdir(repo)
        runner = CliRunner()
        result = runner.invoke(
            app, ["run"], env={**os.environ, "ANTHROPIC_API_KEY": "sk"}
        )
        assert result.exit_code == 5

    def test_in_process_missing_input_md_exits_6(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e",
        }
        _git(repo, "init", "-q", "-b", "feature/x", env=env)
        (repo / ".a2sdlc").mkdir()
        (repo / ".a2sdlc" / "config.yaml").write_text(
            "mode: local\nadapters:\n  work: local-file\n  review: local\n"
            "required_env: [ANTHROPIC_API_KEY]\n"
        )
        (repo / "README").write_text("x\n")
        _git(repo, "add", "-A", env=env)
        _git(repo, "commit", "-q", "-m", "init", env=env)
        monkeypatch.chdir(repo)
        runner = CliRunner()
        result = runner.invoke(
            app, ["run"], env={**os.environ, "ANTHROPIC_API_KEY": "sk"}
        )
        assert result.exit_code == 6

    def test_resolve_base_subprocess_error_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)

        def _boom(*_a, **_k):
            raise subprocess.CalledProcessError(
                1, ["git", "rev-parse"], stderr="git broke"
            )

        monkeypatch.setattr(run_module, "_resolve_base", _boom)
        monkeypatch.chdir(repo)
        runner = CliRunner()
        result = runner.invoke(
            app, ["run"], env={**os.environ, "ANTHROPIC_API_KEY": "sk"}
        )
        assert result.exit_code == 1
        assert "failed to read current branch" in result.stderr

    def test_run_module_main_smoke(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Cover the standalone ``main`` entry point. Use --help to
        # avoid actually running anything.
        with pytest.raises(SystemExit) as exc:
            run_module.main(["--help"])
        assert exc.value.code == 0
