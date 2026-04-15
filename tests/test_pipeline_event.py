"""Tests for PipelineEvent shape — trigger_stage + is_feedback."""

from __future__ import annotations

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.models import StageName


class TestPipelineEventShape:
    def test_trigger_stage_field_exists(self) -> None:
        event = PipelineEvent(key="42", trigger_stage=StageName.SPEC)
        assert event.trigger_stage == StageName.SPEC

    def test_trigger_stage_defaults_to_none(self) -> None:
        event = PipelineEvent(key="42")
        assert event.trigger_stage is None

    def test_is_feedback_defaults_to_false(self) -> None:
        event = PipelineEvent(key="42", trigger_stage=StageName.SPEC)
        assert event.is_feedback is False

    def test_is_feedback_can_be_set(self) -> None:
        event = PipelineEvent(key="42", is_feedback=True)
        assert event.is_feedback is True

    def test_pr_number_still_works(self) -> None:
        event = PipelineEvent(key="42", trigger_stage=StageName.REVIEW, pr_number=7)
        assert event.pr_number == 7

    def test_no_stage_field(self) -> None:
        """Old 'stage' field should not exist."""
        event = PipelineEvent(key="42")
        assert not hasattr(event, "stage") or "stage" not in event.__dataclass_fields__

    def test_no_is_resume_field(self) -> None:
        """Old 'is_resume' field should not exist."""
        event = PipelineEvent(key="42")
        assert "is_resume" not in event.__dataclass_fields__
