"""Shared ``gh`` CLI helper used by GitHub adapters."""

from __future__ import annotations

import subprocess


def gh(args: list[str], input_text: str | None = None) -> str:
    """Run a ``gh`` CLI command and return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        check=True,
        input=input_text,
    )
    return result.stdout.strip()
