"""Stage registry — auto-built from stage classes, validated at import."""

from __future__ import annotations

from typing import Union

from a2sdlc.config import PipelineFlags
from a2sdlc.models import StageName, StageStatus, Transition
from a2sdlc.stages.implement import ImplementStage
from a2sdlc.stages.merge import MergeStage
from a2sdlc.stages.review import ReviewStage
from a2sdlc.stages.spec import SpecStage

AnyStage = Union[SpecStage, ImplementStage, ReviewStage, MergeStage]

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


def next_stage(
    current: StageName,
    status: StageStatus,
    flags: PipelineFlags,
) -> StageName | None:
    """Pure function: determine the next stage from the transition table.

    Returns the next stage name, or None if the pipeline should wait.
    """
    stage = get_stage(current)
    transition = stage.transitions.get(status)
    if transition is None:
        return None
    if transition.next is None:
        return None
    if transition.gate is not None and not getattr(flags, transition.gate):
        return None  # gate closed — wait for human
    return transition.next


def get_transition(
    current: StageName,
    status: StageStatus,
) -> Transition | None:
    """Look up the transition for a given stage + status."""
    stage = get_stage(current)
    return stage.transitions.get(status)


# ── Validate completeness at import ────────────────────────────────


def _validate_stages() -> None:
    for cls in _ALL_STAGES:
        for status in cls.valid_statuses:
            if status not in cls.transitions:
                msg = (
                    f"Stage {cls.name}: status {status!r} is in valid_statuses "
                    f"but has no transition defined"
                )
                raise AssertionError(msg)


_validate_stages()
