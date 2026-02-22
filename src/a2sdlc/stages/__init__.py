"""Stage registry — auto-built from stage classes."""

from __future__ import annotations

from typing import Union

from a2sdlc.stages.implement import ImplementStage
from a2sdlc.stages.merge import MergeStage
from a2sdlc.stages.review import ReviewStage
from a2sdlc.stages.spec import SpecStage

AnyStage = Union[SpecStage, ImplementStage, ReviewStage, MergeStage]

_ALL_STAGES: list[type[AnyStage]] = [SpecStage, ImplementStage, ReviewStage, MergeStage]

# Auto-built from each class's .name attribute — no magic strings.
STAGES: dict[str, type[AnyStage]] = {cls.name: cls for cls in _ALL_STAGES}


def get_stage(name: str) -> AnyStage:
    """Get a stage instance by name."""
    cls = STAGES.get(name)
    if cls is None:
        msg = f"Unknown stage: {name!r}. Available: {list(STAGES.keys())}"
        raise ValueError(msg)
    return cls()
