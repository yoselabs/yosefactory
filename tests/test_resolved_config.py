"""Tests for ResolvedConfig — the materialized 5-layer config collapse."""

from __future__ import annotations

import pytest

from a2sdlc.config import (
    AdaptersConfig,
    QualityConfig,
    ResolvedConfig,
    StageConfig,
)
from a2sdlc.domain.models import GateConfig, GateMode, StageName


@pytest.mark.unit
class TestResolvedConfigDefaults:
    def test_defaults(self) -> None:
        rc = ResolvedConfig()
        assert rc.workflow_name == "default"
        assert rc.base_branch == "main"
        assert rc.stages == {}
        assert isinstance(rc.gates, GateConfig)
        assert isinstance(rc.quality, QualityConfig)
        assert isinstance(rc.adapters, AdaptersConfig)
        assert rc.self_answer is False
        assert rc.model == "claude-sonnet-4-6"
        assert rc.effort is None
        assert rc.max_cost_usd_per_ticket == pytest.approx(15.0)


@pytest.mark.unit
class TestResolvedConfigConstruction:
    def test_per_stage_config(self) -> None:
        spec_cfg = StageConfig(name="spec", max_turns=30)
        rc = ResolvedConfig(stages={StageName.SPEC: spec_cfg})
        assert rc.stages[StageName.SPEC].max_turns == 30

    def test_overrides_preserve_unrelated_defaults(self) -> None:
        rc = ResolvedConfig(workflow_name="review-only", max_cost_usd_per_ticket=5.0)
        assert rc.workflow_name == "review-only"
        assert rc.base_branch == "main"
        assert rc.max_cost_usd_per_ticket == pytest.approx(5.0)

    def test_gate_override(self) -> None:
        rc = ResolvedConfig(gates=GateConfig(merge=GateMode.AUTO))
        assert rc.gates.merge is GateMode.AUTO
        assert rc.gates.spec is GateMode.AUTO  # default


@pytest.mark.unit
class TestResolvedConfigImmutability:
    def test_frozen(self) -> None:
        # frozen=True — assignment must raise.
        rc = ResolvedConfig()
        with pytest.raises(Exception):
            rc.base_branch = "develop"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(Exception):
            ResolvedConfig(unknown_field="x")  # ty: ignore[unknown-argument]


@pytest.mark.unit
class TestResolvedConfigRoundTrip:
    def test_json_round_trip(self) -> None:
        rc = ResolvedConfig(
            workflow_name="review-only",
            base_branch="develop",
            stages={StageName.SPEC: StageConfig(name="spec", max_turns=30)},
            max_cost_usd_per_ticket=5.0,
        )
        restored = ResolvedConfig.model_validate_json(rc.model_dump_json())
        assert restored.workflow_name == "review-only"
        assert restored.base_branch == "develop"
        assert restored.stages[StageName.SPEC].max_turns == 30
        assert restored.max_cost_usd_per_ticket == pytest.approx(5.0)
