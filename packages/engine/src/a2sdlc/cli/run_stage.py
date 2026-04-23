"""``a2sdlc run-stage`` subcommand — local stage runner.

Drives a single pipeline stage against a local checkout using the
file-backed adapters (``local_file`` work, ``local_noop`` review,
``local_branch`` git). Session id is supplied explicitly, inferred from
the current branch name, or generated as a fresh ULID. The corresponding
``a2sdlc/<session_id>`` branch is created or checked out and ``dispatch``
is invoked. Stage lifecycle events are forwarded to the configured
progress adapter so live consoles (rich, GH actions) can render them.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import typer
from ulid import ULID

from a2sdlc.adapters.review import LocalNoopReviewAdapter
from a2sdlc.assembly.composition import (
    CompositionProfile,
    build_adapters,
    build_subscribers,
    validate_profile,
)
from a2sdlc.observability.wire import build_progress_state
from a2sdlc.config import load_config_file
from a2sdlc.domain.exceptions import BlockedError
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.evaluation.tracked_run import run_tracked
from a2sdlc.domain.run_context import RunContext
from a2sdlc.pipeline.dispatch import dispatch

if TYPE_CHECKING:
    from a2sdlc.adapters.runner import StageRunner

logger = logging.getLogger("a2sdlc.cli.run_stage")


# ── Helpers ───────────────────────────────────────────────────────────


def _git_head_sha(root: Path) -> str:
    """Return the short commit SHA at HEAD, or ``"unknown"`` if git fails."""
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _is_dirty(root: Path) -> bool:
    """Return True if the working tree has uncommitted changes."""
    r = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
    )
    return bool(r.stdout.strip())


def _infer_session_id(project_root: Path) -> str | None:
    """Return the session id implied by the current branch, or None."""
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


# ── Core ──────────────────────────────────────────────────────────────


def _run_stage_impl(
    stage: StageName,
    project_root: Path,
    *,
    session: str | None,
    ticket: Path | None,
    no_track: bool,
    runner: StageRunner | None = None,
) -> int:
    """Run a single pipeline stage. Returns an exit code."""
    session_id = session or _infer_session_id(project_root) or str(ULID())
    cfg = load_config_file(project_root)

    from a2sdlc.evaluation.telemetry import (  # noqa: PLC0415
        NoopTelemetry,
        Telemetry,
        local_fallback_telemetry,
    )

    telemetry: Telemetry = (
        NoopTelemetry()
        if no_track
        else local_fallback_telemetry(experiment_name=project_root.name)
    )

    if stage == StageName.SPEC and ticket is None:
        existing_ticket = project_root / ".a2sdlc" / "state" / "ticket.md"
        if not existing_ticket.exists():
            print(  # noqa: T201
                "error: --ticket is required on first SPEC invocation "
                "(no existing .a2sdlc/state/ticket.md found)",
                file=sys.stderr,
            )
            return 2

    # cfg.adapters.* are plain ``str`` (user-supplied); the profile slots
    # are ``Literal[...]``. Validation happens in ``validate_profile`` +
    # the factory's per-name arms — cast at the boundary.
    profile = CompositionProfile(
        work=cast(Any, cfg.adapters.work),
        review=cast(Any, cfg.adapters.review),
        git=cast(Any, cfg.adapters.git),
        progress_subscribers=("gh_comment",),
        credential_profile="github_token",
    )
    validate_profile(profile)

    progress_state = build_progress_state(
        project_root, cfg.adapters.progress, with_mlflow_trace=telemetry.traces_enabled
    )
    work, git, review = build_adapters(
        profile,
        project_root=project_root,
        session_id=session_id,
        stage=stage,
        ticket_path=ticket,
        env={},
    )
    make_comment_subscriber = build_subscribers(profile, progress_state, env={})

    if runner is None:
        from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

        runner = SdkStageRunner(effort=cfg.effort)

    branch_name = f"a2sdlc/{session_id}"
    try:
        git.setup_branch(branch_name, cfg.default_base)
    except BlockedError as exc:
        print(f"error: branch setup failed: {exc.reason}", file=sys.stderr)  # noqa: T201
        return 1

    ctx = RunContext(
        work=work,
        git=git,
        review=review,
        runner=runner,
        progress_state=progress_state,
        config=cfg,
        project_root=project_root,
        logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
        make_comment_subscriber=make_comment_subscriber,
    )

    result: DispatchResult | None = None
    quality = None
    ok = False
    try:
        result, quality = run_tracked(
            dispatch_fn=lambda: dispatch(ctx),
            telemetry=telemetry,
            stage=stage,
            session_id=session_id,
            project_root=project_root,
            quality_command=cfg.quality.check_command,
            sha_before=_git_head_sha(project_root),
            dirty=_is_dirty(project_root),
        )
    finally:
        ok = result is not None and not result.blocked and result.error is None

    if ok and isinstance(review, LocalNoopReviewAdapter):
        review.mark_feedback_consumed()

    if ok and quality is not None and not quality.passed:
        ok = False

    _print_post_run(stage, session_id, project_root, result)
    return 0 if ok else 1


# ── Subcommand + test shim ────────────────────────────────────────────


def run_stage_command(
    stage: Annotated[StageName, typer.Argument(help="Stage to run.")],
    repo: Annotated[
        Path,
        typer.Argument(help="Path to the repo root.", exists=True, file_okay=False),
    ],
    session: Annotated[
        str | None, typer.Option("--session", help="Session id override.")
    ] = None,
    ticket: Annotated[
        Path | None,
        typer.Option("--ticket", help="Ticket markdown file (required on first SPEC)."),
    ] = None,
    no_track: Annotated[
        bool, typer.Option("--no-track", help="Skip MLflow + quality gate tracking.")
    ] = False,
) -> None:
    """Run a single pipeline stage against a local repo."""
    rc = _run_stage_impl(
        stage=stage,
        project_root=repo.resolve(),
        session=session,
        ticket=ticket,
        no_track=no_track,
    )
    raise typer.Exit(code=rc)


def run_stage_entry(argv: list[str], runner: StageRunner | None = None) -> int:
    """Programmatic entry — argparse-parses ``argv`` for test use.

    Production uses ``run_stage_command`` via the typer app. Tests may inject
    a ``StageRunner`` (e.g. ``FakeStageRunner``) directly rather than through
    a string override, keeping ``src/`` free of imports from ``tests/``.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="a2sdlc run-stage")
    parser.add_argument("stage", choices=[s.value for s in StageName])
    parser.add_argument("--session", default=None)
    parser.add_argument("--ticket", default=None, type=Path)
    parser.add_argument("--no-track", action="store_true")
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)

    return _run_stage_impl(
        stage=StageName(args.stage),
        project_root=args.repo.resolve(),
        session=args.session,
        ticket=args.ticket,
        no_track=args.no_track,
        runner=runner,
    )
