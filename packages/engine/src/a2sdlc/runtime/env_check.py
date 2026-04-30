"""REQUIRED_ENV fail-fast validator. Spec §Fail-fast on missing env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MissingEnvVar:
    name: str
    source: str  # "engine" | "adapter:<name>" | similar


def check_required_env(
    requirements: list[tuple[str, list[str]]],
) -> list[MissingEnvVar]:
    """Returns the list of missing vars. Empty list = all set."""
    missing: list[MissingEnvVar] = []
    for source, names in requirements:
        for name in names:
            if not os.environ.get(name):
                missing.append(MissingEnvVar(name=name, source=source))
    return missing


def format_missing_message(missing: list[MissingEnvVar]) -> str:
    if not missing:
        return ""
    lines = ["error: required environment variables are not set:"]
    width = max(len(m.name) for m in missing)
    for m in missing:
        lines.append(f"  - {m.name:<{width}}  ({m.source})")
    lines.append("set them in your shell or .envrc and try again.")
    return "\n".join(lines)
