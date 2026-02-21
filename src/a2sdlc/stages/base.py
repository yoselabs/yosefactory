"""Base stage protocol — defines what a stage must provide."""

from __future__ import annotations

from typing import Protocol

from a2sdlc.config import StageConfig
from a2sdlc.models import StageAction, StageStatus


class Stage(Protocol):
    """Protocol for pipeline stages.

    Not an ABC — stages don't inherit from this. It's a structural
    type check. Any object with these attributes/methods qualifies.
    """

    name: str
    config: StageConfig
    valid_statuses: frozenset[StageStatus]
    uses_ai: bool

    def resolve(
        self, status: StageStatus, comment_body: str, cost_footer: str
    ) -> StageAction:
        """Given a status from the agent, return the action to take."""
        ...
