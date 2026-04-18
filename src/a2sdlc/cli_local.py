"""Local runner CLI internals — backs the ``a2sdlc run-stage`` subcommand.

Drives a single pipeline stage against a local checkout using the
file-backed adapters (``local_file`` work, ``local_noop`` review,
``local_branch`` git). Session id is supplied explicitly, inferred from
the current branch name, or generated as a fresh ULID. The corresponding
``a2sdlc/<session_id>`` branch is created or checked out and ``dispatch``
is invoked. Stage lifecycle events are forwarded to the configured
progress adapter so live consoles (rich, GH actions) can render them.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ulid import ULID

from a2sdlc.adapters.factory import (
    build_git_adapter,
    build_review_adapter,
    build_work_adapter,
)
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
from a2sdlc.config import load_config_file
from a2sdlc.domain.exceptions import BlockedError
from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import ProgressState
from a2sdlc.pipeline.dispatch import DispatchContext, DispatchResult, dispatch

if TYPE_CHECKING:
    from a2sdlc.adapters.protocols import StageRunner

logger = logging.getLogger("a2sdlc.cli_local")


# ── Helpers ───────────────────────────────────────────────────────────


def _git_head_sha(root: Path) -> str:
    """Return the short commit SHA at HEAD, or ``"unknown"`` if git fails."""
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _is_dirty(root: Path) -> bool:
    """Return True if the working tree has uncommitted changes."""
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return bool(r.stdout.strip())


def _infer_session_id(project_root: Path) -> str | None:
    """Return the session id implied by the current branch, or None.

    Reads ``git rev-parse --abbrev-ref HEAD`` in *project_root* and strips
    the leading ``a2sdlc/`` prefix when present.
    """
    res = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return None
    branch = res.stdout.strip()
    if branch.startswith("a2sdlc/"):
        return branch.removeprefix("a2sdlc/")
    return None


def _build_runner(
    runner_override: str | None, effort: str | None = None
) -> StageRunner:
    """Construct the StageRunner. ``runner_override='fake'`` is a test hook."""
    if runner_override == "fake":
        # Test-only path. Production code never sets runner_override, so the
        # tests/ import below stays out of the runtime import graph.
        from tests.fakes import FakeStageRunner  # noqa: PLC0415

        return FakeStageRunner()
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

    return SdkStageRunner(effort=effort)


def _print_post_run(
    stage: StageName,
    session_id: str,
    project_root: Path,
    result: DispatchResult | None,
) -> None:
    """Emit a short post-run summary block to stdout."""
    ok = result is not None and not result.blocked and result.error is None
    status = "OK" if ok else "FAIL"
    print(f"\nStage {stage.value} {status}")  # noqa: T201
    print(f"  Session:  {session_id}")  # noqa: T201
    print(f"  Branch:   a2sdlc/{session_id}")  # noqa: T201
    print(f"  State:    {project_root}/.a2sdlc/")  # noqa: T201
    if result is not None and result.error:
        print(f"  Error:    {result.error}")  # noqa: T201


# ── Entry point ───────────────────────────────────────────────────────


def run_stage_entry(argv: list[str], runner_override: str | None = None) -> int:
    """Run a single pipeline stage against a local repo. Returns an exit code."""
    parser = argparse.ArgumentParser(prog="a2sdlc run-stage")
    parser.add_argument("stage", choices=[s.value for s in StageName])
    parser.add_argument("--session", default=None)
    parser.add_argument("--ticket", default=None, type=Path)
    parser.add_argument(
        "--no-track",
        action="store_true",
        help="Skip metric tracking sinks (MLflow, etc.)",
    )
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)

    project_root = args.repo.resolve()
    stage = StageName(args.stage)

    session_id = args.session or _infer_session_id(project_root) or str(ULID())

    cfg = load_config_file(project_root)

    # Telemetry sink — created up front so we fail fast if MLflow is unreachable.
    sink = None
    if not args.no_track:
        # Lazy import so --no-track paths never pay the mlflow import cost.
        from a2sdlc.evaluation.mlflow_sink import MlflowSink  # noqa: PLC0415

        mlflow_uri = f"file://{Path.home() / '.a2sdlc' / 'mlflow'}"
        sink = MlflowSink(tracking_uri=mlflow_uri, experiment_name=project_root.name)
        sink.verify_reachable()

    if stage == StageName.SPEC and args.ticket is None:
        existing_ticket = project_root / ".a2sdlc" / "ticket.md"
        if not existing_ticket.exists():
            print(  # noqa: T201
                "error: --ticket is required on first SPEC invocation "
                "(no existing .a2sdlc/ticket.md found)",
                file=sys.stderr,
            )
            return 2

    work = build_work_adapter(
        cfg.adapters.work,
        project_root=project_root,
        session_id=session_id,
        stage=stage,
        ticket_path=args.ticket,
    )
    review = build_review_adapter(cfg.adapters.review, project_root=project_root)
    git = build_git_adapter(cfg.adapters.git, project_root=project_root)

    # Build ProgressState and attach the configured subscriber.
    progress_state = ProgressState(project_root=str(project_root))
    _progress_adapter_name = cfg.adapters.progress
    if _progress_adapter_name == "gh_actions":
        from a2sdlc.adapters.gh_actions_subscriber import GhActionsLogSubscriber  # noqa: PLC0415

        progress_state.subscribe(GhActionsLogSubscriber())
    elif _progress_adapter_name == "console":
        from a2sdlc.adapters.console_subscriber import ConsoleSubscriber  # noqa: PLC0415

        progress_state.subscribe(ConsoleSubscriber(progress_state))

    runner = _build_runner(runner_override, effort=cfg.effort)

    # Pre-create / checkout the session branch so that subsequent calls can
    # infer the session id from HEAD even when dispatch short-circuits.
    branch_name = f"a2sdlc/{session_id}"
    try:
        git.setup_branch(branch_name, cfg.default_base)
    except BlockedError as exc:
        print(f"error: branch setup failed: {exc.reason}", file=sys.stderr)  # noqa: T201
        return 1

    ctx = DispatchContext(
        work=work,
        git=git,
        review=review,
        runner=runner,
        progress_state=progress_state,
        config=cfg,
        project_root=project_root,
        logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
    )

    sha_before = _git_head_sha(project_root)
    dirty = _is_dirty(project_root)

    result: DispatchResult | None = None
    quality = None
    ok = False
    try:
        if sink is not None:
            with (
                sink.session(session_id) as sess,
                sess.stage_run(stage=stage.value) as child,
            ):
                child.log_tag("git_sha_before", sha_before)
                child.log_tag("dirty_tree_before", "true" if dirty else "false")
                child.log_tag("session_id", session_id)
                result = asyncio.run(dispatch(ctx))
                stats = getattr(result, "stats", None)
                if stats is not None:
                    if hasattr(stats, "tokens_in"):
                        child.log_metric("tokens_in", stats.tokens_in)
                    if hasattr(stats, "tokens_out"):
                        child.log_metric("tokens_out", stats.tokens_out)
                    if hasattr(stats, "cost_usd"):
                        child.log_metric("cost_usd", stats.cost_usd)
                    if hasattr(stats, "num_turns"):
                        child.log_metric("turns", stats.num_turns)
                    if hasattr(stats, "duration_ms"):
                        child.log_metric("duration_ms", stats.duration_ms)
                # Run quality gate inside the stage_run so metrics/artifacts
                # attach to the active MLflow child run.
                if (
                    stage == StageName.IMPLEMENT
                    and result is not None
                    and not result.blocked
                    and result.error is None
                ):
                    from a2sdlc.evaluation.quality_gate import (  # noqa: PLC0415
                        run_quality_gate,
                    )

                    quality = run_quality_gate(
                        project_root=project_root,
                        command=cfg.quality.check_command,
                    )
                    child.log_metric("quality_passed", 1 if quality.passed else 0)
                    import mlflow as _mlflow  # noqa: PLC0415

                    artifact_path = project_root / ".a2sdlc" / "quality.log"
                    artifact_path.parent.mkdir(parents=True, exist_ok=True)
                    artifact_path.write_text(quality.output)
                    _mlflow.log_artifact(str(artifact_path))
        else:
            result = asyncio.run(dispatch(ctx))
            if (
                stage == StageName.IMPLEMENT
                and result is not None
                and not result.blocked
                and result.error is None
            ):
                from a2sdlc.evaluation.quality_gate import (  # noqa: PLC0415
                    run_quality_gate,
                )

                quality = run_quality_gate(
                    project_root=project_root,
                    command=cfg.quality.check_command,
                )
    finally:
        ok = result is not None and not result.blocked and result.error is None

    if ok and isinstance(review, LocalNoopReviewAdapter):
        review.mark_feedback_consumed()

    # Quality-gate failure doesn't block REVIEW, but it does affect CLI exit code.
    if ok and quality is not None and not quality.passed:
        ok = False

    _print_post_run(stage, session_id, project_root, result)
    return 0 if ok else 1
