"""MERGE stage — deterministic squash merge + cleanup. No AI."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName, StageStatus


class MergeStage:
    name = StageName.MERGE
    uses_ai = False
    valid_statuses = frozenset[StageStatus]()
    transitions: dict[StageStatus, StageName | None] = {}  # terminal stage
    config = StageConfig(name="merge", max_turns=0, timeout_minutes=5)
