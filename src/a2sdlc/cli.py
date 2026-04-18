"""CLI entry point — dispatch only."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("a2sdlc.cli")


# ── Logging ──────────────────────────────────────────────────────────


def setup_logging(ticket_key: str, stage: str, project_root: Path) -> None:
    """Configure structured JSON logging to stderr + file."""
    formatter = logging.Formatter(
        '{"ts":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}'
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Stderr handler.
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # File handler.
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
    """Walk up from cwd looking for ``.a2sdlc/`` directory.

    Returns cwd if not found.
    """
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


# ── Argument parsing ─────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="a2sdlc",
        description="Agent-to-SDLC pipeline engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # dispatch subcommand
    dispatch_parser = sub.add_parser("dispatch", help="Run pipeline dispatch")
    dispatch_parser.add_argument("--project-root", type=Path, default=None)
    # Local dev overrides
    dispatch_parser.add_argument(
        "--stage", default=None, help="Override stage (local dev)"
    )
    dispatch_parser.add_argument("--key", default=None, help="Override key (local dev)")
    dispatch_parser.add_argument(
        "--flag",
        action="append",
        default=[],
        help="Override flags (e.g. --flag self_answer)",
    )

    return parser.parse_args(argv)


# ── Main ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    args = parse_args(argv)

    if args.command == "dispatch":
        project_root = args.project_root or find_project_root()

        from a2sdlc.config import load_config_file  # noqa: PLC0415
        from a2sdlc.pipeline.dispatch import DispatchContext, dispatch  # noqa: PLC0415

        config = load_config_file(project_root)
        setup_logging("dispatch", "dispatch", project_root)

        # Construct adapters
        from a2sdlc.adapters.github import (  # noqa: PLC0415
            GitHubReviewAdapter,
            GitHubWorkAdapter,
            connect,
        )

        token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
        repo_name = os.environ.get("GITHUB_REPOSITORY", "")
        repo = connect(repo_name, token)
        work_adapter = GitHubWorkAdapter(repo)
        review_adapter = GitHubReviewAdapter(repo)

        from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415
        from a2sdlc.adapters.progress_gh_actions import (  # noqa: PLC0415
            GhActionsProgressAdapter,
        )
        from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

        git = LocalGitAdapter(project_root)
        progress = GhActionsProgressAdapter()

        ctx = DispatchContext(
            work=work_adapter,
            git=git,
            review=review_adapter,
            runner=SdkStageRunner(progress=progress),
            progress=progress,
            config=config,
            project_root=project_root,
            logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
        )

        try:
            result = asyncio.run(dispatch(ctx))
            if result.blocked:
                logger.error("Dispatch blocked: %s", result.error)
                sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Interrupted")
