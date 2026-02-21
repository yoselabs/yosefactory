"""Stage registry — discover and load stage definitions."""

from __future__ import annotations

from typing import Union

from a2sdlc.stages.implement import ImplementStage
from a2sdlc.stages.merge import MergeStage
from a2sdlc.stages.review import ReviewStage
from a2sdlc.stages.spec import SpecStage

AnyStage = Union[SpecStage, ImplementStage, ReviewStage, MergeStage]

STAGES: dict[str, type[AnyStage]] = {
    "spec": SpecStage,
    "implement": ImplementStage,
    "review": ReviewStage,
    "merge": MergeStage,
}


def get_stage(name: str) -> AnyStage:
    """Get a stage instance by name."""
    cls = STAGES.get(name)
    if cls is None:
        msg = f"Unknown stage: {name!r}. Available: {list(STAGES.keys())}"
        raise ValueError(msg)
    return cls()
