"""Unit tests for ``cli.run_pipeline.drive_pipeline``.

The full end-to-end happy path is exercised by the smoke harness
(``scripts/smoke_local.sh``); here we mock ``StageExecutor`` so the
critical orchestration paths (per-stage commit/push, max-cycles loop,
failure exit codes) are covered without invoking the real Claude SDK.
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
from a2sdlc.domain.models import StageStatus, StageResult
from a2sdlc.domain.stage_execution import ExecutionResult


# ── Test helpers ─────────────────────────────────────────────────────


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
    """Initialize a working repo + bare origin. Returns (repo, origin, base)."""
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
    """Minimal stand-in for ``SdkStageRunner`` driven by a script of outputs."""

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


# ── Tests ────────────────────────────────────────────────────────────


def test_drive_pipeline_happy_path_commits_and_pushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC → IMPLEMENT → REVIEW(approved) commits each stage + pushes."""
    repo, origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    # Patch the SdkStageRunner constructor to inject a scripted one. The
    # StageExecutor inside ``_run_one_stage`` instantiates against the
    # ``runner`` argument we pass in, so we need to swap the class
    # in ``cli.run_pipeline``.
    scripted = _ScriptedRunner(
        [
            (StageStatus.COMPLETE, "spec body"),
            (StageStatus.COMPLETE, "impl body"),
            (StageStatus.APPROVED, "review body"),
        ]
    )
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: scripted,  # noqa: ARG005
    )

    run_branch = "a2sdlc/auto/feature-x/20260430-000000-deadbe"
    cfg = _make_run_config(max_cycles=2)

    run_pipeline_module.drive_pipeline(
        repo=repo,
        config=cfg,
        base=base,
        input_md=b"smoke\n",
        run_branch=run_branch,
        label=None,
    )

    # Branch exists locally and on origin
    head = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert head.stdout.strip() == run_branch
    ls_remote = subprocess.run(
        ["git", "ls-remote", str(origin), run_branch],
        capture_output=True,
        text=True,
        check=True,
    )
    assert ls_remote.stdout.strip()

    # Three commits in the run branch: spec, implement, review.
    log = subprocess.run(
        ["git", "log", "--format=%s", f"{base}..{run_branch}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    subjects = [line for line in log.stdout.strip().splitlines() if line]
    assert any(s.startswith("stage: spec") for s in subjects)
    assert any(s.startswith("stage: implement") for s in subjects)
    assert any(s.startswith("stage: review") for s in subjects)


def test_drive_pipeline_review_cycle_loop_exits_10_when_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two CHANGES_REQUESTED reviews against max_cycles=2 → exit 10."""
    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    scripted = _ScriptedRunner(
        [
            (StageStatus.COMPLETE, "spec"),
            (StageStatus.COMPLETE, "impl1"),
            (StageStatus.CHANGES_REQUESTED, "review1"),
            (StageStatus.COMPLETE, "impl2"),
            (StageStatus.CHANGES_REQUESTED, "review2"),
        ]
    )
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: scripted,  # noqa: ARG005
    )

    cfg = _make_run_config(max_cycles=2)
    run_branch = "a2sdlc/auto/feature-x/20260430-111111-cafe01"

    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base=base,
            input_md=b"x\n",
            run_branch=run_branch,
            label=None,
        )
    assert exc_info.value.exit_code == 10


def test_drive_pipeline_branch_creation_failure_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``git checkout -b`` against a missing base raises typer.Exit(1)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "x.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")

    cfg = _make_run_config()
    with pytest.raises(typer.Exit) as exc_info:
        run_pipeline_module.drive_pipeline(
            repo=repo,
            config=cfg,
            base="nonexistent",
            input_md=b"x",
            run_branch="a2sdlc/auto/x/y-z",
            label=None,
        )
    assert exc_info.value.exit_code == 1


class _MetricRunner:
    """Scripted runner that returns RunResult with non-zero metrics."""

    def __init__(
        self,
        scripts: list[tuple[StageStatus | None, str, dict[str, float | int]]],
    ):
        self._scripts = list(scripts)

    async def run(self, **kwargs):  # noqa: ANN003,ARG002
        from a2sdlc.domain.run_result import RunResult

        if not self._scripts:
            raise RuntimeError("scripted runner exhausted")
        status, output, metrics = self._scripts.pop(0)
        if status is None:
            block = ""
        else:
            block = f'\n```a2sdlc\n{{"status": "{status.value}", "output": ""}}\n```\n'
        return RunResult(
            success=True,
            output=output + block,
            error=None,
            session_id="test",
            total_cost_usd=float(metrics.get("cost", 0.0)),
            duration_ms=int(metrics.get("duration_ms", 0)),
            input_tokens=int(metrics.get("tokens_in", 0)),
            output_tokens=int(metrics.get("tokens_out", 0)),
            num_turns=int(metrics.get("num_turns", 0)),
            progress=None,
        )


def test_drive_pipeline_aggregate_stats_in_run_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RunEnd.aggregate_stats sums metrics across SPEC/IMPLEMENT/REVIEW stages."""
    from a2sdlc.domain.progress import ProgressEvent, ProgressState, RunEnd

    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    runner = _MetricRunner(
        [
            (
                StageStatus.COMPLETE,
                "spec body",
                {
                    "cost": 0.10,
                    "duration_ms": 1000,
                    "tokens_in": 100,
                    "tokens_out": 50,
                    "num_turns": 2,
                },
            ),
            (
                StageStatus.COMPLETE,
                "impl body",
                {
                    "cost": 0.20,
                    "duration_ms": 2000,
                    "tokens_in": 200,
                    "tokens_out": 80,
                    "num_turns": 3,
                },
            ),
            (
                StageStatus.APPROVED,
                "review body",
                {
                    "cost": 0.05,
                    "duration_ms": 500,
                    "tokens_in": 40,
                    "tokens_out": 20,
                    "num_turns": 1,
                },
            ),
        ]
    )
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: runner,  # noqa: ARG005
    )

    captured: list[RunEnd] = []

    class _Capture:
        async def handle(self, event: ProgressEvent) -> None:
            if isinstance(event, RunEnd):
                captured.append(event)

    from typing import Any

    real_init = ProgressState.__init__

    def _patched_init(self: ProgressState, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        self.subscribe(_Capture())

    monkeypatch.setattr(ProgressState, "__init__", _patched_init)

    cfg = _make_run_config(max_cycles=2)
    run_pipeline_module.drive_pipeline(
        repo=repo,
        config=cfg,
        base=base,
        input_md=b"smoke\n",
        run_branch="a2sdlc/auto/feature-x/20260430-222222-c2",
        label=None,
    )

    assert len(captured) == 1
    agg = captured[0].aggregate_stats
    assert agg.cost_usd == pytest.approx(0.35)
    assert agg.tokens_in == 340
    assert agg.tokens_out == 150
    assert agg.duration_ms == 3500
    assert agg.num_turns == 6


def test_branch_state_dir_uses_double_underscore(tmp_path: Path) -> None:
    """Slashes in run-branch names map to ``__`` for the state dir slug."""
    got = run_pipeline_module._branch_state_dir(
        tmp_path, "a2sdlc/auto/feature-x/20260430-000000-abc123"
    )
    assert got.name == "a2sdlc__auto__feature-x__20260430-000000-abc123"
    assert got.parent.name == "state"


# Type-check: extract_result helper sanity guard for the scripted output
def test_scripted_runner_emits_extractable_block() -> None:
    from a2sdlc.domain.models import extract_result

    block = '\n```a2sdlc\n{"status": "approved", "output": ""}\n```\n'
    result = extract_result(block)
    assert isinstance(result, StageResult)
    assert result.status == StageStatus.APPROVED


class _CapturingRunner:
    """Records every ``ticket_key`` it sees so tests can assert that
    cycle 2+ invocations never collide on the deterministic session ID
    derived via ``get_session_id(ticket_key, stage)``."""

    def __init__(self, scripts: list[tuple[StageStatus | None, str]]):
        self._scripts = list(scripts)
        self.invocations: list[tuple[str, str, bool]] = []

    async def run(self, **kwargs):  # noqa: ANN003
        from a2sdlc.domain.run_result import RunResult

        self.invocations.append(
            (
                str(kwargs.get("ticket_key", "")),
                str(kwargs.get("stage", "")),
                bool(kwargs.get("is_resume", False)),
            )
        )
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


def test_handover_loop_produces_distinct_session_ids_per_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycle 2 IMPLEMENT must use a session-id distinct from cycle 1.

    The runner derives the SDK session id via
    ``get_session_id(ticket_key, stage)``. If both cycles share the
    same ``ticket_key``, the SDK CLI rejects the second
    ``--session-id`` (a session with that ID already exists) and exits
    non-zero — observed in production smoke as a 0-second SDK
    ``ProcessError`` on the cycle-2 IMPLEMENT.

    Asserts: the cycle-2 IMPLEMENT invocation's ticket_key differs from
    cycle 1's, AND the runner is never called with ``is_resume=True``
    against a stale (cross-cycle) session.
    """
    from a2sdlc.config import get_session_id

    repo, _origin, base = _init_local_repo(tmp_path)
    monkeypatch.chdir(repo)

    captured = _CapturingRunner(
        [
            (StageStatus.COMPLETE, "spec"),
            (StageStatus.COMPLETE, "impl1"),
            (StageStatus.CHANGES_REQUESTED, "review1"),
            (StageStatus.COMPLETE, "impl2"),
            (StageStatus.APPROVED, "review2"),
        ]
    )
    monkeypatch.setattr(
        "a2sdlc.pipeline.runner.SdkStageRunner",
        lambda **kw: captured,  # noqa: ARG005
    )

    cfg = _make_run_config(max_cycles=3)
    run_pipeline_module.drive_pipeline(
        repo=repo,
        config=cfg,
        base=base,
        input_md=b"x\n",
        run_branch="a2sdlc/auto/feature-x/20260430-333333-cycle",
        label="TEST-1",
    )

    # Filter to IMPLEMENT calls only.
    implement_calls = [c for c in captured.invocations if "implement" in c[1]]
    assert len(implement_calls) == 2, captured.invocations

    tk1, _, resume1 = implement_calls[0]
    tk2, _, resume2 = implement_calls[1]

    # Neither initial-cycle invocation may pass is_resume=True (resume
    # is for follow-up structured-output prompts within one
    # StageExecutor.run, not across handover cycles).
    assert resume1 is False
    assert resume2 is False

    # Distinct ticket_key → distinct deterministic session id.
    assert tk1 != tk2, (tk1, tk2)
    assert get_session_id(tk1, "implement") != get_session_id(tk2, "implement")


__all__ = ["ExecutionResult"]  # silence unused-import if reorganized
