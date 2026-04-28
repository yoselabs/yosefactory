"""``a2sdlc ensure-gate-labels`` — one-time consumer-onboarding helper.

Creates the four ``gate:*`` labels (`gate:merge:human` / `gate:merge:auto`
/ `gate:spec:human` / `gate:spec:auto`) on a GitHub repository so the
label-form gate parser in ``ingress.resolve_intent`` actually sees them
when consumers apply them via the Issues UI. Idempotent — re-running on
a fully-provisioned repo is a no-op.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated

import typer

logger = logging.getLogger("a2sdlc.cli.ensure_gate_labels")


def ensure_gate_labels_command(
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
) -> None:
    """Create the four ``gate:*`` labels on the target repo if missing."""
    from a2sdlc.adapters.work.gate_labels import ensure_gate_labels  # noqa: PLC0415
    from a2sdlc.adapters.work.github import GitHubWorkAdapter  # noqa: PLC0415

    repo_name = repo or os.environ.get("GITHUB_REPOSITORY")
    if not repo_name:
        raise typer.BadParameter(
            "--repo is required when $GITHUB_REPOSITORY is not set"
        )
    token_value = token or os.environ.get("GITHUB_TOKEN")
    if not token_value:
        raise typer.BadParameter("--token is required when $GITHUB_TOKEN is not set")

    adapter = GitHubWorkAdapter.from_token(token_value, repo_name)
    created = ensure_gate_labels(adapter._repo)  # noqa: SLF001
    if created:
        typer.echo(f"created: {', '.join(created)}")
    else:
        typer.echo("up-to-date: all gate:* labels already exist")
