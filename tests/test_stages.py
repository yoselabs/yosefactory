"""Tests for state machine transitions."""

from __future__ import annotations

import pytest

from a2sdlc.models import GateConfig, GateMode, StageName, StageStatus
from a2sdlc.stages import STAGES, next_stage


# ── State machine transitions ──────────────────────────────────────


@pytest.mark.unit
class TestTransitionCompleteness:
    """Verify next_stage() handles every valid_status for every stage."""

    def test_all_valid_statuses_produce_a_decision(self) -> None:
        """next_stage must return StageName or None for every valid status."""
        gates = GateConfig()
        for stage_cls in STAGES.values():
            stage = stage_cls()
            for status in stage.valid_statuses:
                result = next_stage(stage.name, status, gates)
                assert result is None or isinstance(result, StageName), (
                    f"{stage.name}/{status}: next_stage returned {result!r}"
                )

    def test_merge_is_terminal(self) -> None:
        from a2sdlc.stages.merge import MergeStage

        stage = MergeStage()
        assert len(stage.valid_statuses) == 0


@pytest.mark.unit
class TestNextStage:
    """Test the pure next_stage() function with all 8 gate combinations."""

    def test_spec_complete_spec_auto_proceeds_to_implement(self) -> None:
        gates = GateConfig(spec=GateMode.AUTO)
        assert (
            next_stage(StageName.SPEC, StageStatus.COMPLETE, gates)
            == StageName.IMPLEMENT
        )

    def test_spec_complete_spec_human_waits(self) -> None:
        gates = GateConfig(spec=GateMode.HUMAN)
        assert next_stage(StageName.SPEC, StageStatus.COMPLETE, gates) is None

    def test_spec_questions_always_waits(self) -> None:
        gates = GateConfig()
        assert next_stage(StageName.SPEC, StageStatus.QUESTIONS, gates) is None

    def test_implement_complete_always_proceeds_to_review(self) -> None:
        gates = GateConfig()
        assert (
            next_stage(StageName.IMPLEMENT, StageStatus.COMPLETE, gates)
            == StageName.REVIEW
        )

    def test_implement_questions_always_waits(self) -> None:
        gates = GateConfig()
        assert next_stage(StageName.IMPLEMENT, StageStatus.QUESTIONS, gates) is None

    def test_review_approved_merge_auto_proceeds_to_merge(self) -> None:
        gates = GateConfig(merge=GateMode.AUTO)
        assert (
            next_stage(StageName.REVIEW, StageStatus.APPROVED, gates) == StageName.MERGE
        )

    def test_review_approved_merge_human_waits(self) -> None:
        gates = GateConfig(merge=GateMode.HUMAN)
        assert next_stage(StageName.REVIEW, StageStatus.APPROVED, gates) is None

    def test_review_changes_requested_always_loops_to_implement(self) -> None:
        gates = GateConfig()
        assert (
            next_stage(StageName.REVIEW, StageStatus.CHANGES_REQUESTED, gates)
            == StageName.IMPLEMENT
        )

    def test_unknown_status_returns_none(self) -> None:
        gates = GateConfig()
        # APPROVED is not a valid status for spec
        assert next_stage(StageName.SPEC, StageStatus.APPROVED, gates) is None
