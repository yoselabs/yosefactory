"""Tests for the StageHandler Protocol shape."""

from __future__ import annotations

from typing import Any

import pytest

from a2sdlc.domain.block_reason import BlockReason, Generic
from a2sdlc.domain.effects import Effect
from a2sdlc.domain.models import StageName, StageStatus
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.stages.handler import StageHandler


class _MinimalHandler:
    """A bare-bones class that structurally satisfies StageHandler."""

    name = StageName.SPEC
    valid_statuses = frozenset({StageStatus.COMPLETE})

    def preconditions(self, ctx: Any) -> BlockReason | None:
        return None

    async def execute(self, ctx: Any) -> StageOutcome:
        return StageOutcome(status=StageStatus.COMPLETE, output_text="ok")

    def effects(self, ctx: Any, outcome: StageOutcome) -> list[Effect]:
        return []


class _BlockingHandler:
    """Handler whose preconditions always block — used for the precondition test."""

    name = StageName.REVIEW
    valid_statuses = frozenset({StageStatus.APPROVED, StageStatus.CHANGES_REQUESTED})

    def preconditions(self, ctx: Any) -> BlockReason | None:
        return Generic(message="testing — never runs")

    async def execute(self, ctx: Any) -> StageOutcome:  # pragma: no cover
        raise AssertionError("execute must not run when preconditions block")

    def effects(self, ctx: Any, outcome: StageOutcome) -> list[Effect]:
        return []


@pytest.mark.unit
class TestStageHandlerProtocol:
    """Structural typing — any class with the right shape is a StageHandler."""

    def test_minimal_class_conforms(self) -> None:
        h: StageHandler = _MinimalHandler()
        assert h.name is StageName.SPEC
        assert StageStatus.COMPLETE in h.valid_statuses

    def test_blocking_handler_conforms(self) -> None:
        h: StageHandler = _BlockingHandler()
        reason = h.preconditions(ctx=None)
        assert reason is not None
        assert reason.as_comment() == "testing — never runs"

    def test_preconditions_is_pure(self) -> None:
        h = _MinimalHandler()
        # Calling twice with same ctx yields same result (pure function).
        assert h.preconditions(ctx=None) == h.preconditions(ctx=None)

    def test_effects_default_empty_in_p2(self) -> None:
        # In P2, effects() returns []. P3 swaps this to a real ADT + arms.
        h = _MinimalHandler()
        outcome = StageOutcome(status=StageStatus.COMPLETE)
        assert h.effects(ctx=None, outcome=outcome) == []

    @pytest.mark.asyncio
    async def test_execute_is_async_and_returns_stage_outcome(self) -> None:
        h = _MinimalHandler()
        outcome = await h.execute(ctx=None)
        assert isinstance(outcome, StageOutcome)
        assert outcome.status is StageStatus.COMPLETE
