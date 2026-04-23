"""``a2sdlc dispatch`` subcommand — GitHub-backed pipeline dispatch."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

logger = logging.getLogger("a2sdlc.cli.dispatch")


# ── Logging ──────────────────────────────────────────────────────────


# LogRecord attributes that are not user-provided `extra={...}` fields.
# Anything not in this set (and not starting with "_") is treated as an extra
# and serialized into the JSON output.
_STANDARD_LOGRECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class _JsonFormatter(logging.Formatter):
    """JSON log formatter that preserves `extra={...}` kwargs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(ticket_key: str, stage: str, project_root: Path) -> None:
    """Configure structured JSON logging to stderr + file."""
    formatter = _JsonFormatter()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    log_dir = project_root / ".a2sdlc" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = log_dir / f"{ticket_key}-{stage}-{ts}.log"
    file_handler = logging.FileHandler(str(log_file))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


# ── GH-native run_id derivation ──────────────────────────────────────


def _derive_github_native_run_id() -> str | None:
    """Deterministic run_id for the ``ci-github-native`` profile.

    Combines the triggering event's unique identifier (label.id, comment.id,
    review.id) with GITHUB_SHA so that the same delivery arriving twice
    short-circuits via state-level idempotency, while two different events
    for the same (ticket, stage, sha) still both run.

    Returns None if the event payload isn't structured as expected — callers
    treat None as "no idempotency guarantee this run" rather than failing.
    """
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if not event_path or not Path(event_path).exists():
        return None
    try:
        import json  # noqa: PLC0415

        with open(event_path) as f:
            event = json.load(f)
    except (OSError, ValueError):
        return None

    sha = os.environ.get("GITHUB_SHA", "")
    key = str(
        event.get("issue", {}).get("number")
        or event.get("pull_request", {}).get("number")
        or ""
    )
    trigger_id = ""
    if event_name == "issues":
        trigger_id = f"label-{event.get('label', {}).get('id', '')}"
    elif event_name == "issue_comment":
        trigger_id = f"comment-{event.get('comment', {}).get('id', '')}"
    elif event_name == "pull_request":
        trigger_id = f"pr-label-{event.get('label', {}).get('id', '')}"
    elif event_name == "pull_request_review":
        trigger_id = f"review-{event.get('review', {}).get('id', '')}"
    elif event_name == "pull_request_review_comment":
        trigger_id = f"review-comment-{event.get('comment', {}).get('id', '')}"
    if not key or not trigger_id:
        return None
    return f"{key}:{trigger_id}:{sha[:12]}"


# ── Project root discovery ───────────────────────────────────────────


def find_project_root() -> Path:
    """Walk up from cwd looking for ``.a2sdlc/`` directory; return cwd if not found."""
    cwd = Path.cwd()
    current = cwd
    while True:
        if (current / ".a2sdlc").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return cwd


# ── Subcommand ───────────────────────────────────────────────────────


def dispatch_command(
    project_root: Annotated[
        Path | None,
        typer.Option("--project-root", help="Path to repo root (defaults to cwd)."),
    ] = None,
    stage: Annotated[
        str | None, typer.Option("--stage", help="Override stage (local dev).")
    ] = None,  # noqa: ARG001
    key: Annotated[
        str | None, typer.Option("--key", help="Override ticket key (local dev).")
    ] = None,  # noqa: ARG001
    flag: Annotated[
        list[str] | None,
        typer.Option("--flag", help="Override flag (e.g. --flag self_answer)."),
    ] = None,  # noqa: ARG001
) -> None:
    """Run pipeline dispatch against a GitHub-backed work adapter."""
    root = project_root or find_project_root()

    from a2sdlc.assembly.composition import (  # noqa: PLC0415
        build_adapters,
        build_subscribers,
        resolve_composition_profile,
        validate_profile,
    )
    from a2sdlc.assembly.wire import build_progress_state  # noqa: PLC0415
    from a2sdlc.config import load_config_file  # noqa: PLC0415
    from a2sdlc.domain.models import StageName  # noqa: PLC0415
    from a2sdlc.domain.run_context import RunContext  # noqa: PLC0415
    from a2sdlc.evaluation.telemetry import telemetry_from_env  # noqa: PLC0415
    from a2sdlc.pipeline.dispatch import dispatch  # noqa: PLC0415
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

    config = load_config_file(root)
    setup_logging("dispatch", "dispatch", root)

    telemetry = telemetry_from_env(experiment_name=root.name)
    progress_state = build_progress_state(
        root,
        config.adapters.progress,
        with_mlflow_trace=telemetry.traces_enabled,
    )

    profile = resolve_composition_profile(os.environ, mode="dispatch")
    validate_profile(profile)

    work_adapter, git, review_adapter = build_adapters(
        profile,
        project_root=root,
        session_id="dispatch",
        stage=StageName.SPEC,
        env=os.environ,
    )
    make_comment_subscriber = build_subscribers(profile, progress_state, env=os.environ)

    run_id = (
        os.environ.get("RUN_ID")
        if profile.work == "workflow_input"
        else _derive_github_native_run_id()
    )

    ctx = RunContext(
        work=work_adapter,
        git=git,
        review=review_adapter,
        runner=SdkStageRunner(effort=config.effort),
        progress_state=progress_state,
        config=config,
        project_root=root,
        logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
        make_comment_subscriber=make_comment_subscriber,
        telemetry=telemetry,
        run_id=run_id,
    )

    try:
        result = asyncio.run(dispatch(ctx))
        if result.blocked:
            logger.error("Dispatch blocked: %s", result.error)
            _notify_stage_failure(ctx, result.error or "unknown", profile)
            raise typer.Exit(code=1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        # Full traceback stays in the CI job log (useful for debugging).
        # The issue gets a short, actionable comment pointing at the run.
        logger.exception("dispatch.unhandled_exception")
        _notify_stage_failure(ctx, f"{type(exc).__name__}: {exc}", profile)
        raise typer.Exit(code=1) from exc


def _notify_stage_failure(ctx, reason: str, profile) -> None:
    """Post a short "stage failed" comment on the ticket + set the blocked label.

    Best-effort — a failure here must not mask the original error.
    Dispatcher-profile runs route failures over HTTP via their own
    subscriber, so this helper is a no-op there.
    """
    if profile.work == "workflow_input":
        return
    try:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if not event_path:
            return
        import json  # noqa: PLC0415

        with open(event_path) as f:
            event = json.load(f)
        key = str(
            event.get("issue", {}).get("number")
            or event.get("pull_request", {}).get("number")
            or ""
        )
        if not key:
            return
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run_id_env = os.environ.get("GITHUB_RUN_ID", "")
        run_url = f"{server}/{repo}/actions/runs/{run_id_env}" if run_id_env else ""
        marker = f"Stage failed: {reason}" + (
            f" — see run: {run_url}" if run_url else ""
        )
        ctx.work.mark_blocked(key, marker)
    except Exception:  # noqa: BLE001
        logger.warning("stage_failure_notify_failed", exc_info=True)
