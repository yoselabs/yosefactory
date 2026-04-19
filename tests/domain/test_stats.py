"""Tests for a2sdlc.evaluation.stats — StageRunStats accumulator."""

from __future__ import annotations

import pytest

from a2sdlc.domain.run_result import RunResult
from a2sdlc.domain.stats import StageRunStats


@pytest.mark.unit
class TestStageRunStatsDefaults:
    def test_all_fields_default_to_zero(self) -> None:
        stats = StageRunStats()
        assert stats.cost_usd == 0
        assert stats.tokens_in == 0
        assert stats.tokens_out == 0
        assert stats.duration_ms == 0
        assert stats.num_turns == 0


@pytest.mark.unit
class TestStageRunStatsAddFromResult:
    def _make_result(
        self,
        *,
        cost: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        duration_ms: int = 0,
        num_turns: int = 0,
    ) -> RunResult:
        return RunResult(
            success=True,
            total_cost_usd=cost,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            duration_ms=duration_ms,
            num_turns=num_turns,
        )

    def test_add_single_result(self) -> None:
        stats = StageRunStats()
        result = self._make_result(
            cost=0.05, tokens_in=100, tokens_out=200, duration_ms=3000, num_turns=4
        )
        stats.add_from_result(result)
        assert stats.cost_usd == 0.05
        assert stats.tokens_in == 100
        assert stats.tokens_out == 200
        assert stats.duration_ms == 3000
        assert stats.num_turns == 4

    def test_add_two_results_accumulates(self) -> None:
        stats = StageRunStats()
        r1 = self._make_result(
            cost=0.05, tokens_in=100, tokens_out=200, duration_ms=3000, num_turns=4
        )
        r2 = self._make_result(
            cost=0.03, tokens_in=50, tokens_out=80, duration_ms=1500, num_turns=2
        )
        stats.add_from_result(r1)
        stats.add_from_result(r2)
        assert stats.cost_usd == pytest.approx(0.08)
        assert stats.tokens_in == 150
        assert stats.tokens_out == 280
        assert stats.duration_ms == 4500
        assert stats.num_turns == 6


@pytest.mark.unit
class TestStageRunStatsReset:
    def test_reset_zeros_all_fields(self) -> None:
        stats = StageRunStats()
        result = RunResult(
            success=True,
            total_cost_usd=1.0,
            input_tokens=500,
            output_tokens=300,
            duration_ms=10000,
            num_turns=10,
        )
        stats.add_from_result(result)
        # Verify it was accumulated
        assert stats.cost_usd == 1.0
        # Now reset
        stats.reset()
        assert stats.cost_usd == 0
        assert stats.tokens_in == 0
        assert stats.tokens_out == 0
        assert stats.duration_ms == 0
        assert stats.num_turns == 0
