"""Post-implement quality gate — runs a user-configured check command."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QualityResult:
    """Outcome of a single quality-gate invocation."""

    passed: bool
    exit_code: int
    output: str


def run_quality_gate(project_root: Path, command: str) -> QualityResult:
    """Execute ``command`` in ``project_root`` via the shell.

    Returns a :class:`QualityResult` with ``passed`` set to ``True`` iff the
    command exited with status 0. ``output`` contains combined stdout+stderr.
    ``shell=True`` is intentional — ``command`` is a user-configured string
    (``quality.check_command``) that may include pipes, redirections, etc.
    """
    result = subprocess.run(  # noqa: S602 — user-configured command by design
        command,
        shell=True,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    return QualityResult(
        passed=result.returncode == 0,
        exit_code=result.returncode,
        output=combined,
    )
