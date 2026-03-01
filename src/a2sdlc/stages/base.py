"""Base stage protocol — defines what a stage must provide."""

from __future__ import annotations

from typing import Protocol

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName, StageStatus, Transition


class Stage(Protocol):
    """Protocol for pipeline stages.

    Not an ABC — stages don't inherit from this. It's a structural
    type check. Any object with these attributes/methods qualifies.
    """

    name: StageName
    config: StageConfig
    valid_statuses: frozenset[StageStatus]
    transitions: dict[StageStatus, Transition]
    uses_ai: bool
