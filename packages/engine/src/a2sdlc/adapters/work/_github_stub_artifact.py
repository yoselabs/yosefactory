"""Defensive write_stage_artifact stub for GitHubWorkAdapter.

The GH ecosystem follow-up spec will replace this with a comment- or
attachment-based write. v1 ships the local ecosystem only; this stub
exists so the WorkAdapter Protocol is satisfied for dev-mode invocations
that touch the GH adapter. Lives in its own module to keep github.py
under the 500-line limit.
"""

from __future__ import annotations

from pathlib import Path

from a2sdlc.domain.models import StageName


def write_stage_artifact_stub(stage: StageName, cycle: int, content: str) -> Path:
    """Mirror LocalFileWorkAdapter behavior under .a2sdlc/state/github-stub/."""
    if stage == StageName.SPEC:
        filename = "spec.md"
    elif stage == StageName.IMPLEMENT:
        filename = f"implement-cycle-{cycle}.md"
    else:
        raise ValueError(
            f"GitHubWorkAdapter does not write artifacts for stage {stage!r}"
        )
    state_root = Path(".a2sdlc/state/github-stub")
    state_root.mkdir(parents=True, exist_ok=True)
    path = state_root / filename
    path.write_text(content)
    return path
