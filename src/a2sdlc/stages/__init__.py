"""Stage registry — auto-built from stage classes, validated at import."""

from __future__ import annotations

from a2sdlc.models import GateConfig, GateMode, StageName, StageStatus
from a2sdlc.stages.implement import ImplementStage
from a2sdlc.stages.merge import MergeStage
from a2sdlc.stages.review import ReviewStage
from a2sdlc.stages.spec import SpecStage

AnyStage = SpecStage | ImplementStage | ReviewStage | MergeStage

_ALL_STAGES: list[type[AnyStage]] = [SpecStage, ImplementStage, ReviewStage, MergeStage]

STAGES: dict[StageName, type[AnyStage]] = {cls.name: cls for cls in _ALL_STAGES}


def get_stage(name: StageName | str) -> AnyStage:
    """Get a stage instance by name."""
    try:
        key = StageName(name) if isinstance(name, str) else name
    except ValueError:
        msg = f"Unknown stage: {name!r}. Available: {[s.value for s in StageName]}"
        raise ValueError(msg) from None
    cls = STAGES.get(key)
    if cls is None:
        msg = f"Unknown stage: {name!r}. Available: {[s.value for s in StageName]}"
        raise ValueError(msg)
    return cls()


# ── Transition logic ────────────────────────────────────────────────


def next_stage(
    current: StageName,
    status: StageStatus,
    gates: GateConfig,
) -> StageName | None:
    """Pure function: determine the next stage given current stage, status, and gate config.

    Returns the next stage name, or None if the pipeline should wait for a human.

    Transition table:
    - Spec + complete → IMPLEMENT (always auto)
    - Spec + questions → None
    - Implement + complete + gates.review=AUTO → REVIEW
    - Implement + complete + gates.review=HUMAN → None
    - Implement + questions → None
    - Review + approved + gates.merge=AUTO → MERGE
    - Review + approved + gates.merge=HUMAN → None
    - Review + changes_requested → IMPLEMENT (always loops back)
    """
    match (current, status):
        case (StageName.SPEC, StageStatus.COMPLETE):
            return StageName.IMPLEMENT
        case (StageName.SPEC, StageStatus.QUESTIONS):
            return None
        case (StageName.IMPLEMENT, StageStatus.COMPLETE):
            return StageName.REVIEW if gates.review == GateMode.AUTO else None
        case (StageName.IMPLEMENT, StageStatus.QUESTIONS):
            return None
        case (StageName.REVIEW, StageStatus.APPROVED):
            return StageName.MERGE if gates.merge == GateMode.AUTO else None
        case (StageName.REVIEW, StageStatus.CHANGES_REQUESTED):
            return StageName.IMPLEMENT
        case _:
            return None
