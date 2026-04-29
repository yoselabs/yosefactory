"""``a2sdlc scrub-base`` — remove leaked .a2sdlc/state/state.json from base.

Recovery helper for the manual-merge-bypass case: when somebody clicks
Merge in the UI or runs ``gh pr merge`` from the CLI, the engine's
strip step never fires and state.json gets carried into the base
branch. Run this once to clean up. Idempotent — calling on a clean
base is a no-op.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated

import typer

logger = logging.getLogger("a2sdlc.cli.scrub_base")


def scrub_base_command(
    repo: Annotated[
        str | None,
        typer.Option(
            "--repo",
            help="owner/name (defaults to $GITHUB_REPOSITORY).",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="GitHub App installation token (defaults to $GITHUB_TOKEN).",
        ),
    ] = None,
    base: Annotated[
        str,
        typer.Option("--base", help="Base branch to scrub."),
    ] = "main",
) -> None:
    """Delete .a2sdlc/state/state.json from the base branch if present."""
    from a2sdlc.adapters.work.github import GitHubWorkAdapter  # noqa: PLC0415
    from a2sdlc.adapters.work.scrub_base import scrub_base  # noqa: PLC0415

    repo_name = repo or os.environ.get("GITHUB_REPOSITORY")
    if not repo_name:
        raise typer.BadParameter(
            "--repo is required when $GITHUB_REPOSITORY is not set"
        )
    token_value = token or os.environ.get("GITHUB_TOKEN")
    if not token_value:
        raise typer.BadParameter("--token is required when $GITHUB_TOKEN is not set")

    adapter = GitHubWorkAdapter.from_token(token_value, repo_name)
    scrubbed = scrub_base(adapter._repo, base)  # noqa: SLF001
    if scrubbed:
        typer.echo(f"scrubbed: removed leaked state.json from {base}")
    else:
        typer.echo(f"clean: no leaked state.json on {base}")
