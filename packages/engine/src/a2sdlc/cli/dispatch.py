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


# ── Mode 2 run_id derivation ─────────────────────────────────────────


def _derive_mode2_run_id() -> str | None:
    """Deterministic run_id for GH-native Mode 2 dispatches.

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

    from a2sdlc.config import load_config_file  # noqa: PLC0415
    from a2sdlc.pipeline.dispatch import DispatchContext, dispatch  # noqa: PLC0415

    config = load_config_file(root)
    setup_logging("dispatch", "dispatch", root)

    from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415
    from a2sdlc.assembly.wire import build_progress_state  # noqa: PLC0415
    from a2sdlc.evaluation.telemetry import telemetry_from_env  # noqa: PLC0415
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

    git = LocalGitAdapter(root)
    telemetry = telemetry_from_env(experiment_name=root.name)
    progress_state = build_progress_state(
        root,
        config.adapters.progress,
        with_mlflow_trace=telemetry.traces_enabled,
    )

    # Mode selection is ambient — DISPATCHER_URL signals Jira-dispatcher mode,
    # otherwise we use the existing GH-native composition.
    dispatcher_url = os.environ.get("DISPATCHER_URL")

    if dispatcher_url:
        # ── Mode 1 (dispatcher-driven) ────────────────────────────────
        from a2sdlc.adapters.subscriber.dispatcher_event import (  # noqa: PLC0415
            DispatcherEventSubscriber,
        )
        from a2sdlc.adapters.subscriber.console import ConsoleSubscriber  # noqa: PLC0415
        from a2sdlc.adapters.work.workflow_input import WorkflowInputReader  # noqa: PLC0415
        from github import Github  # noqa: PLC0415
        from a2sdlc.adapters.review import GitHubReviewAdapter  # noqa: PLC0415
        import httpx  # noqa: PLC0415

        work_adapter = WorkflowInputReader()
        # The engine still opens PRs via GH — review adapter needs GH auth,
        # but this is narrowly-scoped to the target repo's GITHUB_TOKEN.
        token = os.environ["GITHUB_TOKEN"]
        repo_name = os.environ["GITHUB_REPOSITORY"]
        review_adapter = GitHubReviewAdapter(Github(token).get_repo(repo_name))

        run_id = os.environ["RUN_ID"]
        run_hmac = os.environ["RUN_HMAC"]
        http = httpx.Client(timeout=30.0)
        dispatcher_sub = DispatcherEventSubscriber(
            dispatcher_url=dispatcher_url,
            run_id=run_id,
            run_hmac=run_hmac,
            http=http,
        )
        progress_state.subscribe(dispatcher_sub)

        # Dispatcher mode: comments flow to Jira via DispatcherEventSubscriber.
        # We still need *some* comment subscriber per DispatchContext contract —
        # ConsoleSubscriber is harmless local stdout, not tracker-bound.
        def make_comment_subscriber(_comment):
            return ConsoleSubscriber(progress_state)
    else:
        # ── Mode 2 / legacy CI (GH-native) ────────────────────────────
        from github import Github  # noqa: PLC0415
        from a2sdlc.adapters.review import GitHubReviewAdapter  # noqa: PLC0415
        from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber  # noqa: PLC0415
        from a2sdlc.adapters.work import GitHubWorkAdapter  # noqa: PLC0415

        token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
        # The GHA default token (`ghs_`-prefixed GITHUB_TOKEN) can't trigger
        # workflow re-runs from bot label writes, so the engine's state
        # machine stalls silently. Fail loud instead.
        if token.startswith("ghs_"):
            raise typer.BadParameter(
                "GITHUB_TOKEN looks like the GHA default (`ghs_`-prefixed). "
                "The engine needs a GitHub App or PAT — bot events from the "
                "default token don't re-trigger workflows, breaking the "
                "stage machine. Configure A2SDLC_APP_ID / A2SDLC_APP_PRIVATE_KEY "
                "and pass the derived token as GITHUB_TOKEN."
            )
        repo_name = os.environ.get("GITHUB_REPOSITORY", "")
        repo = Github(token).get_repo(repo_name)
        work_adapter = GitHubWorkAdapter(repo)
        review_adapter = GitHubReviewAdapter(repo)

        # Derive a deterministic run_id so duplicate event deliveries (GHA
        # re-runs, webhook redelivery) are caught by state-level idempotency
        # instead of re-executing the stage. GITHUB_SHA is the commit the
        # event was triggered against; combined with the ticket key this
        # dedupes the common "same event fired twice" cases.
        mode2_run_id = _derive_mode2_run_id()

        def make_comment_subscriber(comment):
            return GhCommentSubscriber(comment, progress_state)

    ctx = DispatchContext(
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
        run_id=run_id if dispatcher_url else mode2_run_id,
    )

    try:
        result = asyncio.run(dispatch(ctx))
        if result.blocked:
            logger.error("Dispatch blocked: %s", result.error)
            _notify_stage_failure(ctx, result.error or "unknown", dispatcher_url)
            raise typer.Exit(code=1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        # Full traceback stays in the CI job log (useful for debugging).
        # The issue gets a short, actionable comment pointing at the run.
        logger.exception("dispatch.unhandled_exception")
        _notify_stage_failure(ctx, f"{type(exc).__name__}: {exc}", dispatcher_url)
        raise typer.Exit(code=1) from exc


def _notify_stage_failure(ctx, reason: str, dispatcher_url: str | None) -> None:
    """Post a short "stage failed" comment on the ticket and set the blocked
    label. Best-effort — a failure here must not mask the original error."""
    # Mode 1 (Jira dispatcher) routes comments over HTTP; let it handle
    # failures via its own subscriber. This helper is Mode-2 only.
    if dispatcher_url:
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
