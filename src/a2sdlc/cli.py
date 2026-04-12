"""CLI entry point — dispatch only."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from importlib.resources import files as pkg_files

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


# ── Prompt assembly ──────────────────────────────────────────────────


def _read_if_exists(path: Path) -> str:
    """Read file contents if it exists, else return empty string."""
    if path.is_file():
        return path.read_text()
    return ""


def _sorted_md_files(directory: Path) -> list[Path]:
    """Return sorted list of .md files in directory."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"))


def assemble_system_prompt(stage: str, a2sdlc_dir: Path) -> str:
    """Load and concatenate prompt files for a stage.

    Check project dir first (overrides), fall back to package-bundled prompts.
    """
    parts: list[str] = []

    project_prompts = a2sdlc_dir / "prompts"

    # Try to resolve package prompts directory.
    try:
        pkg_prompts_base = pkg_files("a2sdlc.prompts")
        # Convert to a real path for filesystem operations.
        pkg_prompts = Path(str(pkg_prompts_base))
    except (ModuleNotFoundError, TypeError):
        pkg_prompts = None

    # 1. system.md
    system_text = _read_if_exists(project_prompts / "system.md")
    if not system_text and pkg_prompts:
        system_text = _read_if_exists(pkg_prompts / "system.md")
    if system_text:
        parts.append(system_text)

    # 2. adapters/*.md (sorted)
    adapter_files = _sorted_md_files(project_prompts / "adapters")
    if not adapter_files and pkg_prompts:
        adapter_files = _sorted_md_files(pkg_prompts / "adapters")
    for f in adapter_files:
        content = f.read_text()
        if content:
            parts.append(content)

    # 3. stages/{stage}.md
    stage_text = _read_if_exists(project_prompts / "stages" / f"{stage}.md")
    if not stage_text and pkg_prompts:
        stage_text = _read_if_exists(pkg_prompts / "stages" / f"{stage}.md")
    if stage_text:
        parts.append(stage_text)

    return "\n\n".join(parts)


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
        help="Override flags (e.g. --flag auto_spec)",
    )

    return parser.parse_args(argv)


# ── Main ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    args = parse_args(argv)

    if args.command == "dispatch":
        project_root = args.project_root or find_project_root()

        from a2sdlc.config import load_config_file  # noqa: PLC0415
        from a2sdlc.dispatch import DispatchContext, dispatch  # noqa: PLC0415

        config = load_config_file(project_root)
        setup_logging("dispatch", "dispatch", project_root)

        # Construct adapters
        if config.adapter == "github":
            from a2sdlc.adapters.github import GitHubTicketAdapter  # noqa: PLC0415

            token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            tickets = GitHubTicketAdapter(repo_name=repo, token=token)
        else:
            logger.error("Unknown adapter: %s", config.adapter)
            sys.exit(1)

        from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415
        from a2sdlc.runner import run_stage as _run_stage  # noqa: PLC0415

        git = LocalGitAdapter(project_root)

        from collections.abc import Callable  # noqa: PLC0415

        from a2sdlc.config import StageConfig  # noqa: PLC0415
        from a2sdlc.models import StageName  # noqa: PLC0415
        from a2sdlc.runner import RunResult  # noqa: PLC0415

        class _SdkRunner:
            async def run(
                self,
                user_prompt: str,
                system_prompt: str,
                config: StageConfig,
                ticket_key: str,
                stage: StageName,
                project_root: str,
                is_resume: bool = False,
                on_progress: Callable[[str], None] | None = None,
                branch: str = "",
            ) -> RunResult:
                return await _run_stage(
                    user_prompt=user_prompt,
                    system_prompt=system_prompt,
                    config=config,
                    ticket_key=ticket_key,
                    stage=stage,
                    project_root=project_root,
                    is_resume=is_resume,
                    on_progress=on_progress,
                    branch=branch,
                )

        ctx = DispatchContext(
            work=tickets,  # ty: ignore[invalid-argument-type]  # TODO(task-16): split
            git=git,
            review=tickets,  # ty: ignore[invalid-argument-type]  # TODO(task-16): split
            runner=_SdkRunner(),
            config=config,
            project_root=project_root,
            logger=logging.getLogger("a2sdlc.dispatch"),
        )

        try:
            result = asyncio.run(dispatch(ctx))
            if result.blocked:
                logger.error("Dispatch blocked: %s", result.error)
                sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Interrupted")
