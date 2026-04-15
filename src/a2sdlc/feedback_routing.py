"""Feedback routing — maps current pipeline stage to target stage for feedback events."""

from __future__ import annotations

from a2sdlc.models import StageName


def resolve_target_stage(current_stage: StageName | None) -> StageName:
    """Given the pipeline's current stage, return which stage should handle feedback.

    - No stage or SPEC: feedback is spec-level (no code exists yet)
    - IMPLEMENT or later: feedback is implementation-level (code exists, fix it)
    """
    if current_stage is None or current_stage == StageName.SPEC:
        return StageName.SPEC
    return StageName.IMPLEMENT
