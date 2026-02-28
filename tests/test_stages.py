"""Tests for individual stage resolve() methods and state machine transitions."""

from __future__ import annotations

import pytest

from a2sdlc.config import PipelineFlags
from a2sdlc.models import Gate, StageName, StageStatus
from a2sdlc.stages import STAGES, get_transition, next_stage
from a2sdlc.stages.implement import ImplementStage
from a2sdlc.stages.review import ReviewStage
from a2sdlc.stages.spec import SpecStage


@pytest.mark.unit
class TestSpecResolve:
    def test_complete(self) -> None:
        stage = SpecStage()
        action = stage.resolve(StageStatus.COMPLETE, "Spec done.", "---\ncost")
        assert "Spec done." in action.comment
        assert action.write_state == ("spec", "complete")
        assert action.transition_to is None

    def test_questions(self) -> None:
        stage = SpecStage()
        action = stage.resolve(StageStatus.QUESTIONS, "1. What?", "---\ncost")
        assert "What?" in action.comment
        assert action.transition_to == "needs-input"
        assert action.write_state is None


@pytest.mark.unit
class TestImplementResolve:
    def test_complete(self) -> None:
        stage = ImplementStage()
        action = stage.resolve(StageStatus.COMPLETE, "PR created.", "---\ncost")
        assert action.write_state == ("implement", "complete")

    def test_questions(self) -> None:
        stage = ImplementStage()
        action = stage.resolve(StageStatus.QUESTIONS, "Plan gap.", "---\ncost")
        assert action.transition_to == "needs-input"


@pytest.mark.unit
class TestReviewResolve:
    def test_approved_no_merge(self) -> None:
        stage = ReviewStage()
        action = stage.resolve(
            StageStatus.APPROVED, "LGTM", "---\ncost", auto_merge=False, pr_number=42
        )
        assert action.merge_pr is None
        assert action.post_review == (42, "LGTM", "APPROVE")

    def test_approved_auto_merge(self) -> None:
        stage = ReviewStage()
        action = stage.resolve(
            StageStatus.APPROVED, "LGTM", "---\ncost", auto_merge=True, pr_number=42
        )
        assert action.merge_pr == 42
        assert action.post_review == (42, "LGTM", "APPROVE")

    def test_approved_no_pr_number(self) -> None:
        stage = ReviewStage()
        action = stage.resolve(
            StageStatus.APPROVED, "LGTM", "---\ncost", auto_merge=True
        )
        assert action.merge_pr is None
        assert action.post_review is None

    def test_changes_requested(self) -> None:
        stage = ReviewStage()
        action = stage.resolve(
            StageStatus.CHANGES_REQUESTED,
            "Fix SQL injection",
            "---\ncost",
            pr_number=42,
        )
        assert action.transition_to == "needs-fix"
        assert action.post_review == (42, "Fix SQL injection", "REQUEST_CHANGES")

    def test_valid_statuses(self) -> None:
        stage = ReviewStage()
        assert StageStatus.APPROVED in stage.valid_statuses
        assert StageStatus.CHANGES_REQUESTED in stage.valid_statuses
        assert StageStatus.COMPLETE not in stage.valid_statuses


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
            for status, t in stage.transitions.items():
                if t.next is not None:
                    assert t.next in valid_names, (
                        f"{stage.name}/{status}: targets unknown {t.next}"
                    )

    def test_all_gates_are_valid_flag_names(self) -> None:
        flag_fields = {f for f in PipelineFlags.__dataclass_fields__}
        for stage_cls in STAGES.values():
            stage = stage_cls()
            for status, t in stage.transitions.items():
                if t.gate is not None:
                    assert t.gate in flag_fields, (
                        f"{stage.name}/{status}: gate {t.gate} not in PipelineFlags"
                    )

    def test_merge_is_terminal(self) -> None:
        from a2sdlc.stages.merge import MergeStage

        stage = MergeStage()
        assert len(stage.transitions) == 0
        assert len(stage.valid_statuses) == 0


@pytest.mark.unit
class TestNextStage:
    """Test the pure next_stage() function with all flag combinations."""

    def test_spec_complete_auto_proceed(self) -> None:
        flags = PipelineFlags(auto_proceed=True)
        assert (
            next_stage(StageName.SPEC, StageStatus.COMPLETE, flags)
            == StageName.IMPLEMENT
        )

    def test_spec_complete_gate_closed(self) -> None:
        flags = PipelineFlags(auto_proceed=False)
        assert next_stage(StageName.SPEC, StageStatus.COMPLETE, flags) is None

    def test_spec_questions_always_waits(self) -> None:
        flags = PipelineFlags(auto_proceed=True)
        assert next_stage(StageName.SPEC, StageStatus.QUESTIONS, flags) is None

    def test_implement_complete_always_reviews(self) -> None:
        flags = PipelineFlags()
        assert (
            next_stage(StageName.IMPLEMENT, StageStatus.COMPLETE, flags)
            == StageName.REVIEW
        )

    def test_implement_questions_waits(self) -> None:
        flags = PipelineFlags()
        assert next_stage(StageName.IMPLEMENT, StageStatus.QUESTIONS, flags) is None

    def test_review_approved_auto_merge(self) -> None:
        flags = PipelineFlags(auto_merge=True)
        assert (
            next_stage(StageName.REVIEW, StageStatus.APPROVED, flags) == StageName.MERGE
        )

    def test_review_approved_gate_closed(self) -> None:
        flags = PipelineFlags(auto_merge=False)
        assert next_stage(StageName.REVIEW, StageStatus.APPROVED, flags) is None

    def test_review_changes_requested_loops_to_implement(self) -> None:
        flags = PipelineFlags()
        result = next_stage(StageName.REVIEW, StageStatus.CHANGES_REQUESTED, flags)
        assert result == StageName.IMPLEMENT

    def test_unknown_status_returns_none(self) -> None:
        flags = PipelineFlags()
        # APPROVED is not a valid status for spec
        assert next_stage(StageName.SPEC, StageStatus.APPROVED, flags) is None


@pytest.mark.unit
class TestGetTransition:
    def test_spec_complete_has_gate(self) -> None:
        t = get_transition(StageName.SPEC, StageStatus.COMPLETE)
        assert t is not None
        assert t.gate == Gate.AUTO_PROCEED
        assert t.next == StageName.IMPLEMENT

    def test_implement_complete_no_gate(self) -> None:
        t = get_transition(StageName.IMPLEMENT, StageStatus.COMPLETE)
        assert t is not None
        assert t.gate is None
        assert t.next == StageName.REVIEW

    def test_review_approved_has_merge_gate(self) -> None:
        t = get_transition(StageName.REVIEW, StageStatus.APPROVED)
        assert t is not None
        assert t.gate == Gate.AUTO_MERGE

    def test_invalid_combo_returns_none(self) -> None:
        t = get_transition(StageName.SPEC, StageStatus.APPROVED)
        assert t is None

    def test_transitions_have_labels(self) -> None:
        t = get_transition(StageName.SPEC, StageStatus.COMPLETE)
        assert t is not None
        assert t.label == "stage:implement"

    def test_transitions_have_jira_status(self) -> None:
        t = get_transition(StageName.IMPLEMENT, StageStatus.COMPLETE)
        assert t is not None
        assert t.jira_status == "In Review"
