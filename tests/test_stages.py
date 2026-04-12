"""Tests for state machine transitions."""

from __future__ import annotations

import pytest

from a2sdlc.models import GateConfig, GateMode, StageName, StageStatus
from a2sdlc.stages import STAGES, next_stage


# ── State machine transitions ──────────────────────────────────────


@pytest.mark.unit
class TestTransitionTable:
    """Every valid_status must have a transition. Checked at import, but
    also tested explicitly for safety."""

    def test_all_stages_have_transitions_for_valid_statuses(self) -> None:
        for stage_cls in STAGES.values():
            stage = stage_cls()
            for status in stage.valid_statuses:
                assert status in stage.transitions, (
                    f"{stage.name}: missing transition for {status}"
                )

    def test_all_transitions_target_valid_stages(self) -> None:
        valid_names = set(StageName)
        for stage_cls in STAGES.values():
            stage = stage_cls()
            for status, target in stage.transitions.items():
                if target is not None:
                    assert target in valid_names, (
                        f"{stage.name}/{status}: targets unknown {target}"
                    )

    def test_merge_is_terminal(self) -> None:
        from a2sdlc.stages.merge import MergeStage

        stage = MergeStage()
        assert len(stage.transitions) == 0
        assert len(stage.valid_statuses) == 0


@pytest.mark.unit
class TestNextStage:
    """Test the pure next_stage() function with all 8 gate combinations."""

    def test_spec_complete_always_proceeds_to_implement(self) -> None:
        gates = GateConfig()
        assert (
            next_stage(StageName.SPEC, StageStatus.COMPLETE, gates)
            == StageName.IMPLEMENT
        )

    def test_spec_questions_always_waits(self) -> None:
        gates = GateConfig()
        assert next_stage(StageName.SPEC, StageStatus.QUESTIONS, gates) is None

    def test_implement_complete_review_auto_proceeds_to_review(self) -> None:
        gates = GateConfig(review=GateMode.AUTO)
        assert (
            next_stage(StageName.IMPLEMENT, StageStatus.COMPLETE, gates)
            == StageName.REVIEW
        )

    def test_implement_complete_review_human_waits(self) -> None:
        gates = GateConfig(review=GateMode.HUMAN)
        assert next_stage(StageName.IMPLEMENT, StageStatus.COMPLETE, gates) is None

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
