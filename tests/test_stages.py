"""Tests for individual stage resolve() methods."""

from __future__ import annotations

import pytest

from a2sdlc.models import StageStatus
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
