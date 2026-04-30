"""Failure-path tests for ``cli.run_pipeline.drive_pipeline``.

Split out from ``test_run_pipeline.py`` to keep each file under the
500-line file-length lint cap. The happy path + max-cycles loop live in
the sibling file; this one drives the SPEC / IMPLEMENT / REVIEW
agent-failure branches plus commit/push failure exit codes.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import typer

from a2sdlc.cli import run_pipeline as run_pipeline_module
from a2sdlc.config_run import RunConfig
from a2sdlc.domain.models import StageStatus


def _git(repo: Path, *args: str) -> None:
    full_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@e",
    }
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=full_env,
    )


def _init_local_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    repo.mkdir()
    origin.mkdir()
    _git(origin, "init", "-q", "--bare")
    _git(repo, "init", "-q", "-b", "feature/x")
    (repo / ".a2sdlc").mkdir()
    (repo / ".a2sdlc" / "config.yaml").write_text(
        textwrap.dedent(
            """\
            mode: local
            adapters:
              work: local-file
              review: local
            required_env: []
            pipeline:
              max_review_cycles: 2
              protected_bases: [main]
            """
        )
    )
    (repo / "INPUT.md").write_text("smoke task\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "feature/x")
    return repo, origin, "feature/x"


def _make_run_config(max_cycles: int = 2) -> RunConfig:
    return RunConfig.model_validate(
        {
            "mode": "local",
            "adapters": {"work": "local-file", "review": "local"},
            "required_env": [],
            "pipeline": {"max_review_cycles": max_cycles, "protected_bases": ["main"]},
        }
    )


class _ScriptedRunner:
    def __init__(self, scripts: list[tuple[StageStatus | None, str]]):
        self._scripts = list(scripts)

    async def run(self, **kwargs):  # noqa: ANN003,ARG002
        from a2sdlc.domain.run_result import RunResult

        if not self._scripts:
            raise RuntimeError("scripted runner exhausted")
        status, output = self._scripts.pop(0)
        if status is None:
            block = ""
        else:
            block = f'\n```a2sdlc\n{{"status": "{status.value}", "output": ""}}\n```\n'
        return RunResult(
            success=True,
            output=output + block,
            error=None,
            session_id="test",
            progress=None,
        )


class _FailingRunner:
    """Stand-in runner that returns ``RunResult(success=False)`` after a
    prefix of successes. Drives the SPEC / IMPLEMENT / REVIEW failure
    branches in ``drive_pipeline``."""

    def __init__(self, scripts: list[tuple[StageStatus | None, str, bool]]):
        self._scripts = list(scripts)

    async def run(self, **kwargs):  # noqa: ANN003,ARG002
        from a2sdlc.domain.run_result import RunResult

        if not self._scripts:
            raise RuntimeError("scripted runner exhausted")
        status, output, ok = self._scripts.pop(0)
        if status is None:
            block = ""
        else:
            block = f'\n```a2sdlc\n{{"status": "{status.value}", "output": ""}}\n```\n'
        return RunResult(
            success=ok,
            output=output + block,
            error=None if ok else "agent_failure",
            session_id="test",
            progress=None,
        )


def test_drive_pipeline_spec_failure_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _FailingRunner([(StageStatus.COMPLETE, "spec", False)])
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: runner,  # noqa: ARG005
    )

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x",
            run_branch="a2sdlc/auto/feature-x/20260430-spec-fail",
            label=None,
        )
    assert exc_info.value.exit_code == 1


def test_drive_pipeline_implement_failure_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _FailingRunner(
        [
            (StageStatus.COMPLETE, "spec", True),
            (StageStatus.COMPLETE, "impl", False),
        ]
    )
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: runner,  # noqa: ARG005
    )

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x",
            run_branch="a2sdlc/auto/feature-x/20260430-impl-fail",
            label=None,
        )
    assert exc_info.value.exit_code == 1


def test_drive_pipeline_review_failure_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _FailingRunner(
        [
            (StageStatus.COMPLETE, "spec", True),
            (StageStatus.COMPLETE, "impl", True),
            (StageStatus.APPROVED, "review", False),
        ]
    )
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: runner,  # noqa: ARG005
    )

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x",
            run_branch="a2sdlc/auto/feature-x/20260430-review-fail",
            label=None,
        )
    assert exc_info.value.exit_code == 1


def test_drive_pipeline_internal_exception_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain Exception escaping ``_drive`` becomes typer.Exit(1)."""
    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    succeeding = _ScriptedRunner([(StageStatus.COMPLETE, "spec")])
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: succeeding,  # noqa: ARG005
    )

    def _explode(*_a, **_k):
        raise RuntimeError("commit-internals-broken")

    monkeypatch.setattr(run_pipeline_module, "_commit_and_push", _explode)

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x",
            run_branch="a2sdlc/auto/feature-x/20260430-internal-exc",
            label=None,
        )
    assert exc_info.value.exit_code == 1


def test_drive_pipeline_push_failure_exits_9(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _ScriptedRunner([(StageStatus.COMPLETE, "spec")])
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: runner,  # noqa: ARG005
    )

    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):
        if (
            isinstance(cmd, list)
            and len(cmd) >= 2
            and cmd[0] == "git"
            and cmd[1] == "push"
        ):

            class _R:
                returncode = 1
                stderr = "boom"
                stdout = ""

            return _R()
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(run_pipeline_module.subprocess, "run", _fake_run)

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x",
            run_branch="a2sdlc/auto/feature-x/20260430-push-fail",
            label=None,
        )
    assert exc_info.value.exit_code == 9


def test_drive_pipeline_commit_failure_exits_8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _ScriptedRunner([(StageStatus.COMPLETE, "spec")])
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: runner,  # noqa: ARG005
    )

    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):
        if (
            isinstance(cmd, list)
            and len(cmd) >= 2
            and cmd[0] == "git"
            and cmd[1] == "commit"
        ):

            class _R:
                returncode = 1
                stderr = "commit-boom"
                stdout = ""

            return _R()
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(run_pipeline_module.subprocess, "run", _fake_run)

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x",
            run_branch="a2sdlc/auto/feature-x/20260430-commit-fail",
            label=None,
        )
    assert exc_info.value.exit_code == 8


def test_drive_pipeline_emits_run_end_on_failure_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RunEnd fires on the failure path too — single-loop driver (C3).

    Subscribes a capture handler before drive_pipeline runs; asserts a
    single RunEnd event with success=False reaches the bus even when
    SPEC fails. Implicitly proves both pipeline + run_end execute in
    one event loop because the subscriber registered on the first loop
    is still reachable when run_end is emitted.
    """
    from typing import Any

    from a2sdlc.domain.progress import ProgressEvent, ProgressState, RunEnd

    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _FailingRunner([(StageStatus.COMPLETE, "spec", False)])
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: runner,  # noqa: ARG005
    )

    captured: list[RunEnd] = []

    class _Capture:
        async def handle(self, event: ProgressEvent) -> None:
            if isinstance(event, RunEnd):
                captured.append(event)

    real_init = ProgressState.__init__

    def _patched_init(self: ProgressState, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        self.subscribe(_Capture())

    monkeypatch.setattr(ProgressState, "__init__", _patched_init)

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x",
            run_branch="a2sdlc/auto/feature-x/20260430-c3-runend",
            label=None,
        )
    assert exc_info.value.exit_code == 1
    assert len(captured) == 1
    assert captured[0].success is False
    assert captured[0].error is not None
