"""CLI entry point — orchestrate, prompt assembly, merge."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from importlib.resources import files as pkg_files

from a2sdlc.adapters import get_code_adapter, get_ticket_adapter
from a2sdlc.config import load_config, load_project
from a2sdlc.runner import run_stage
from a2sdlc.verifier import verify_and_act

from a2sdlc.stages import STAGES as _STAGE_REGISTRY

logger = logging.getLogger("a2sdlc.cli")

_STAGES = tuple(_STAGE_REGISTRY.keys()) + ("auto",)


# ── Logging ──────────────────────────────────────────────────────────


def setup_logging(ticket_key: str, agent: str, project_root: Path) -> None:
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
    log_file = log_dir / f"{ticket_key}-{agent}-{ts}.log"
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

    # run subcommand
    run_parser = sub.add_parser("run", help="Run a pipeline stage")
    run_parser.add_argument("stage", choices=_STAGES, help="Pipeline stage to run")
    run_parser.add_argument(
        "--source", required=True, help="Ticket source adapter name"
    )
    run_parser.add_argument("--key", required=True, help="Ticket key (e.g. PROJ-42)")
    run_parser.add_argument("--pr", type=int, default=None, help="PR number")
    run_parser.add_argument("--model", default=None, help="Override model")
    run_parser.add_argument(
        "--max-turns", type=int, default=None, help="Override max turns"
    )
    run_parser.add_argument(
        "--supervised", action="store_true", help="Enable supervised mode"
    )
    run_parser.add_argument(
        "--dry-run", action="store_true", help="Print prompt and config, do not run"
    )

    # merge subcommand
    merge_parser = sub.add_parser("merge", help="Squash-merge a PR and clean up")
    merge_parser.add_argument("--key", required=True, help="Ticket key")
    merge_parser.add_argument("--pr", type=int, required=True, help="PR number")

    # cleanup subcommand
    cleanup_parser = sub.add_parser("cleanup", help="Clean up session files")
    cleanup_parser.add_argument("--key", required=True, help="Ticket key to clean up")

    return parser.parse_args(argv)


# ── Orchestration ────────────────────────────────────────────────────


async def orchestrate(args: argparse.Namespace) -> None:
    """Main orchestration flow for the ``run`` subcommand."""
    # 1. Find project root, load project config.
    project_root = find_project_root()
    project = load_project(project_root)

    # 2. Setup logging.
    setup_logging(args.key, args.stage, project_root)
    logger.info("Starting stage=%s key=%s source=%s", args.stage, args.key, args.source)

    # 3. Initialize adapters.
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    tickets = get_ticket_adapter(project.tickets_adapter, repo=repo)
    code = get_code_adapter(project.code_adapter, repo=repo)

    # 4. Auto stage: fetch status, map to stage.
    stage = args.stage
    if args.source == "jira" and stage == "auto":
        status = tickets.get_status(args.key)
        stage = project.jira_status_map.get(status, "spec")
        logger.info("Auto-mapped Jira status %r to stage %r", status, stage)

    # 5. Load stage config with overrides.
    overrides: dict[str, object] = {}
    if args.model is not None:
        overrides["model"] = args.model
    if args.max_turns is not None:
        overrides["max_turns"] = args.max_turns
    config = load_config(stage, **overrides)

    # 6. Fetch ticket context.
    ticket_context = tickets.fetch(args.key)

    # 7. Assemble system prompt.
    a2sdlc_dir = project_root / ".a2sdlc"
    system_prompt = assemble_system_prompt(stage, a2sdlc_dir)

    # 8. Dry-run: print prompt and config, return.
    if args.dry_run:
        print(f"Stage: {stage}")
        print(f"Config: {config}")
        print(f"System prompt:\n{system_prompt}")
        print(f"Ticket context:\n{ticket_context}")
        return

    # 9. Create progress comment on ticket.
    comment_id = tickets.create_comment(
        args.key,
        f"⏳ **{stage}** stage started…",
    )

    # 10. Progress callback — updates the comment in-process.
    def on_progress(text: str) -> None:
        try:
            tickets.update_comment(args.key, comment_id, text)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to update progress comment", exc_info=True)

    # 11. Run the stage via SDK.
    result = await run_stage(
        user_prompt=ticket_context,
        system_prompt=system_prompt,
        config=config,
        ticket_key=args.key,
        stage=stage,
        project_root=str(project_root),
        on_progress=on_progress,
    )

    # 12. Log result summary.
    logger.info(
        "Run complete: success=%s error=%s cost=$%.4f output_len=%d",
        result.success,
        result.error,
        result.total_cost_usd,
        len(result.output),
    )

    # 13. Call verify_and_act.
    verify_and_act(
        stage=stage,
        result=result,
        ticket_key=args.key,
        tickets=tickets,
        code=code,
        project=project,
        comment_id=comment_id,
    )

    # 14. Log completion.
    logger.info("Orchestration complete for %s/%s", args.key, stage)


# ── Merge ────────────────────────────────────────────────────────────


def do_merge(args: argparse.Namespace) -> None:
    """Squash-merge a PR and clean up."""
    project_root = find_project_root()
    project = load_project(project_root)
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    code = get_code_adapter(project.code_adapter, repo=repo)

    logger.info("Merging PR #%d for %s", args.pr, args.key)
    code.merge_pr(args.pr)
    logger.info("Merged PR #%d", args.pr)

    # Clean up session files.
    session_dir = project_root / ".a2sdlc" / "sessions" / args.key
    if session_dir.exists():
        shutil.rmtree(session_dir)
        logger.info("Cleaned up sessions for %s", args.key)


# ── Main ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Dispatch to orchestrate, merge, or cleanup."""
    args = parse_args(argv)

    if args.command == "cleanup":
        project_root = find_project_root()
        session_dir = project_root / ".a2sdlc" / "sessions" / args.key
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info("Cleaned up sessions for %s", args.key)
        return

    if args.command == "merge":
        do_merge(args)
        return

    # args.command == "run"
    try:
        asyncio.run(orchestrate(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
