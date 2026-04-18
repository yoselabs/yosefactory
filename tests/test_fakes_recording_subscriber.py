"""RecordingSubscriber — minimal test helper that captures all events."""

from __future__ import annotations

import pytest

from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import StageStart
from tests.fakes import RecordingSubscriber


@pytest.mark.asyncio
async def test_recording_subscriber_captures_events_in_order() -> None:
    rec = RecordingSubscriber()
    e1 = StageStart(stage=StageName.SPEC, session_id="a", started_at=0.0)
    e2 = StageStart(stage=StageName.IMPLEMENT, session_id="b", started_at=1.0)
    await rec.handle(e1)
    await rec.handle(e2)
    assert rec.events == [e1, e2]


def test_recording_subscriber_starts_empty() -> None:
    rec = RecordingSubscriber()
    assert rec.events == []
