"""Tests for Event ADT + pipeline_event_to_event bridge."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from a2sdlc.domain.events import (
    Event,
    FeedbackEvent,
    FeedbackSource,
    LabelTriggerEvent,
    ProceedEvent,
    SkipSignal,
    TicketClosedEvent,
    pipeline_event_to_event,
)
from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent


EventAdapter = TypeAdapter(Event)


@pytest.mark.unit
class TestEventRoundTrip:
    """Every variant survives JSON → Event discriminated-union parsing."""

    def test_ticket_closed(self) -> None:
        evt = TicketClosedEvent(key="TEST-1")
        restored = EventAdapter.validate_json(evt.model_dump_json())
        assert isinstance(restored, TicketClosedEvent)
        assert restored.key == "TEST-1"

    def test_label_trigger_issue_side(self) -> None:
        evt = LabelTriggerEvent(key="TEST-1", stage=StageName.SPEC)
        restored = EventAdapter.validate_json(evt.model_dump_json())
        assert isinstance(restored, LabelTriggerEvent)
        assert restored.stage is StageName.SPEC
        assert restored.pr_number is None

    def test_label_trigger_pr_side(self) -> None:
        evt = LabelTriggerEvent(
            key="TEST-1",
            stage=StageName.REVIEW,
            pr_number=42,
        )
        restored = EventAdapter.validate_json(evt.model_dump_json())
        assert isinstance(restored, LabelTriggerEvent)
        assert restored.stage is StageName.REVIEW
        assert restored.pr_number == 42

    def test_feedback(self) -> None:
        evt = FeedbackEvent(
            key="TEST-1",
            source=FeedbackSource.PR_REVIEW,
            pr_number=42,
        )
        restored = EventAdapter.validate_json(evt.model_dump_json())
        assert isinstance(restored, FeedbackEvent)
        assert restored.source is FeedbackSource.PR_REVIEW

    def test_proceed(self) -> None:
        evt = ProceedEvent(key="TEST-1", current_stage=StageName.IMPLEMENT)
        restored = EventAdapter.validate_json(evt.model_dump_json())
        assert isinstance(restored, ProceedEvent)
        assert restored.current_stage is StageName.IMPLEMENT

    def test_skip(self) -> None:
        evt = SkipSignal(reason="no event configured")
        restored = EventAdapter.validate_json(evt.model_dump_json())
        assert isinstance(restored, SkipSignal)
        assert restored.reason == "no event configured"


@pytest.mark.unit
class TestDiscriminator:
    """The 'kind' discriminator is required and drives variant selection."""

    def test_missing_kind_rejected(self) -> None:
        with pytest.raises(Exception):
            EventAdapter.validate_json('{"key":"TEST-1"}')

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(Exception):
            EventAdapter.validate_json('{"kind":"xyz","key":"TEST-1"}')


@pytest.mark.unit
class TestPipelineEventToEvent:
    """Bridge maps today's flag-bag PipelineEvent to the new ADT."""

    def test_is_closed_maps_to_ticket_closed(self) -> None:
        pe = PipelineEvent(key="TEST-1", is_closed=True)
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, TicketClosedEvent)
        assert evt.key == "TEST-1"

    def test_trigger_stage_maps_to_label_trigger(self) -> None:
        pe = PipelineEvent(key="TEST-1", trigger_stage=StageName.SPEC)
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, LabelTriggerEvent)
        assert evt.stage is StageName.SPEC
        assert evt.pr_number is None

    def test_trigger_stage_with_pr_number(self) -> None:
        pe = PipelineEvent(
            key="TEST-1",
            trigger_stage=StageName.REVIEW,
            pr_number=42,
        )
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, LabelTriggerEvent)
        assert evt.stage is StageName.REVIEW
        assert evt.pr_number == 42

    def test_is_feedback_with_pr_number_maps_to_pr_review(self) -> None:
        pe = PipelineEvent(key="TEST-1", is_feedback=True, pr_number=42)
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, FeedbackEvent)
        assert evt.source is FeedbackSource.PR_REVIEW
        assert evt.pr_number == 42

    def test_is_feedback_without_pr_number_maps_to_issue_comment(self) -> None:
        pe = PipelineEvent(key="TEST-1", is_feedback=True)
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, FeedbackEvent)
        assert evt.source is FeedbackSource.ISSUE_COMMENT

    def test_empty_flags_map_to_proceed(self) -> None:
        pe = PipelineEvent(key="TEST-1")
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, ProceedEvent)
        assert evt.key == "TEST-1"

    def test_is_closed_wins_over_other_flags(self) -> None:
        # Defensive: if multiple flags are set, closed takes precedence
        # because a closed ticket skips everything else.
        pe = PipelineEvent(
            key="TEST-1",
            is_closed=True,
            is_feedback=True,
            trigger_stage=StageName.SPEC,
        )
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, TicketClosedEvent)

    def test_trigger_stage_wins_over_is_feedback(self) -> None:
        # Label events take precedence over feedback — a label-flip is
        # the explicit "run this stage" signal.
        pe = PipelineEvent(
            key="TEST-1",
            trigger_stage=StageName.SPEC,
            is_feedback=True,
        )
        evt = pipeline_event_to_event(pe)
        assert isinstance(evt, LabelTriggerEvent)
