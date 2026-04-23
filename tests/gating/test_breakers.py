"""Tests for pipeline circuit breakers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from a2sdlc.config import ProjectConfig, StageConfig
from a2sdlc.domain.models import StageName, TicketState
from a2sdlc.gating.breakers import check_cost_ceiling, check_review_cycles


def _make_state(**kwargs) -> TicketState:
    defaults = {
        "stage": StageName.REVIEW,
        "branch": "agent/1",
        "stage_run_id": "r-1",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(kwargs)
    return TicketState(**defaults)  # ty: ignore[invalid-argument-type]


@pytest.mark.unit
class TestReviewCycles:
    def test_passes_on_non_review_stage(self) -> None:
        cfg = StageConfig(name="spec", max_review_cycles=2)
        state = _make_state(review_cycles=5)
        assert check_review_cycles(StageName.SPEC, state, cfg) is None

    def test_passes_under_limit(self) -> None:
        cfg = StageConfig(name="review", max_review_cycles=2)
        state = _make_state(review_cycles=1)
        assert check_review_cycles(StageName.REVIEW, state, cfg) is None

    def test_trips_at_limit(self) -> None:
        cfg = StageConfig(name="review", max_review_cycles=2)
        state = _make_state(review_cycles=2)
        reason = check_review_cycles(StageName.REVIEW, state, cfg)
        assert reason is not None and "2 review cycles" in reason

    def test_passes_on_no_state(self) -> None:
        cfg = StageConfig(name="review", max_review_cycles=2)
        assert check_review_cycles(StageName.REVIEW, None, cfg) is None


@pytest.mark.unit
class TestCostCeiling:
    def test_passes_under_ceiling(self) -> None:
        config = ProjectConfig(max_cost_usd_per_ticket=15.0)
        state = _make_state(accumulated_cost_usd=3.00)
        assert check_cost_ceiling(state, config) is None

    def test_trips_at_ceiling(self) -> None:
        config = ProjectConfig(max_cost_usd_per_ticket=15.0)
        state = _make_state(accumulated_cost_usd=15.00)
        reason = check_cost_ceiling(state, config)
        assert reason is not None and "15.00" in reason

    def test_trips_over_ceiling(self) -> None:
        config = ProjectConfig(max_cost_usd_per_ticket=15.0)
        state = _make_state(accumulated_cost_usd=22.50)
        reason = check_cost_ceiling(state, config)
        assert reason is not None and "22.50" in reason

    def test_passes_on_no_state(self) -> None:
        config = ProjectConfig(max_cost_usd_per_ticket=15.0)
        assert check_cost_ceiling(None, config) is None
