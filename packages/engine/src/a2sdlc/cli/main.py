"""CLI top-level entry — typer app with ``dispatch`` and ``run-stage`` subcommands."""

from __future__ import annotations

import typer

from a2sdlc.cli.dispatch import dispatch_command
from a2sdlc.cli.ensure_gate_labels import ensure_gate_labels_command
from a2sdlc.cli.run_stage import run_stage_command
from a2sdlc.cli.scrub_base import scrub_base_command

app = typer.Typer(
    name="a2sdlc",
    help="Agent-to-SDLC pipeline engine.",
    add_completion=False,
    no_args_is_help=True,
)

app.command("dispatch", help="Run pipeline dispatch (GitHub Actions entry).")(
    dispatch_command
)
app.command("run-stage", help="Run a single pipeline stage against a local repo.")(
    run_stage_command
)
app.command(
    "ensure-gate-labels",
    help="Create gate:* labels on a GitHub repo (one-time consumer onboarding).",
)(ensure_gate_labels_command)
app.command(
    "scrub-base",
    help="Remove leaked .a2sdlc/state/state.json from a base branch.",
)(scrub_base_command)


def main(argv: list[str] | None = None) -> None:
    """Entry point — delegates to the typer app."""
    app(args=argv, prog_name="a2sdlc", standalone_mode=True)
