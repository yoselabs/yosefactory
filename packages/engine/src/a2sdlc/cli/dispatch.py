"""``a2sdlc dispatch`` subcommand — GitHub-backed pipeline dispatch."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

logger = logging.getLogger("a2sdlc.cli.dispatch")


# ── Logging ──────────────────────────────────────────────────────────


def setup_logging(ticket_key: str, stage: str, project_root: Path) -> None:
    """Configure structured JSON logging to stderr + file."""
    formatter = logging.Formatter(
        '{"ts":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}'
    )

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

    from github import Github  # noqa: PLC0415

    from a2sdlc.adapters.review import GitHubReviewAdapter  # noqa: PLC0415
    from a2sdlc.adapters.work import GitHubWorkAdapter  # noqa: PLC0415

    token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
    repo_name = os.environ.get("GITHUB_REPOSITORY", "")
    repo = Github(token).get_repo(repo_name)
    work_adapter = GitHubWorkAdapter(repo)
    review_adapter = GitHubReviewAdapter(repo)

    from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415
    from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber  # noqa: PLC0415
    from a2sdlc.assembly.wire import build_progress_state  # noqa: PLC0415
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

    git = LocalGitAdapter(root)
    progress_state = build_progress_state(root, config.adapters.progress)

    ctx = DispatchContext(
        work=work_adapter,
        git=git,
        review=review_adapter,
        runner=SdkStageRunner(effort=config.effort),
        progress_state=progress_state,
        config=config,
        project_root=root,
        logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
        make_comment_subscriber=lambda comment: GhCommentSubscriber(
            comment, progress_state
        ),
    )

    try:
        result = asyncio.run(dispatch(ctx))
        if result.blocked:
            logger.error("Dispatch blocked: %s", result.error)
            raise typer.Exit(code=1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
