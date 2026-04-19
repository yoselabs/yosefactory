"""CLI top-level entry — routes between ``dispatch`` and ``run-stage``."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    raw = list(argv) if argv is not None else sys.argv[1:]

    # ``run-stage`` has its own argparse; route raw args to it before the
    # dispatch-only top-level parser sees them.
    if raw and raw[0] == "run-stage":
        from a2sdlc.cli.run_stage import run_stage_entry  # noqa: PLC0415

        sys.exit(run_stage_entry(raw[1:]))

    from a2sdlc.cli.dispatch import dispatch_entry  # noqa: PLC0415

    dispatch_entry(argv)
