"""Tests for ProgressState wiring in dispatch."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.config import ProjectConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult
from a2sdlc.evaluation.progress import GroupClose, GroupOpen, ProgressState, StageEnd
from a2sdlc.pipeline.dispatch import DispatchContext, dispatch
from tests.fakes import (
    FakeGitAdapter,
    FakeReviewAdapter,
    FakeRunner,
    FakeWorkAdapter,
    RecordingSubscriber,
)

_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'


@pytest.mark.asyncio
async def test_dispatch_emits_stage_start_and_stage_end() -> None:
    """GIVEN a dispatch that runs a stage successfully
    WHEN dispatch completes
    THEN StageStart and StageEnd events were emitted to subscribers.
    """
    event = PipelineEvent(key="35", trigger_stage=StageName.SPEC)
    work = FakeWorkAdapter(event=event, ticket_body="Build patient form")
    runner = FakeRunner(
        RunResult(
            success=True,
            output=_COMPLETE_OUTPUT,
            total_cost_usd=0.5,
            input_tokens=1000,
            output_tokens=2000,
            duration_ms=5000,
            num_turns=10,
        )
    )
    progress_state = ProgressState(project_root="/tmp/test")
    subscriber = RecordingSubscriber()
    progress_state.subscribe(subscriber)

    ctx = DispatchContext(
        work=work,
        git=FakeGitAdapter(),
        review=FakeReviewAdapter(),
        runner=runner,
        progress_state=progress_state,
        config=ProjectConfig(),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id="run-progress",
    )

    await dispatch(ctx)

    event_types = [type(e).__name__ for e in subscriber.events]
    assert "StageStart" in event_types, f"StageStart missing from {event_types}"
    assert "StageEnd" in event_types, f"StageEnd missing from {event_types}"


@pytest.mark.asyncio
async def test_dispatch_emits_group_open_and_close_for_agent_output() -> None:
    """GIVEN a dispatch that runs a stage successfully
    WHEN dispatch completes
    THEN GroupOpen and GroupClose events were emitted for the agent-output block.
    """
    event = PipelineEvent(key="35", trigger_stage=StageName.SPEC)
    work = FakeWorkAdapter(event=event, ticket_body="Build patient form")
    runner = FakeRunner(
        RunResult(
            success=True,
            output=_COMPLETE_OUTPUT,
            total_cost_usd=0.5,
            input_tokens=1000,
            output_tokens=2000,
            duration_ms=5000,
            num_turns=10,
        )
    )
    progress_state = ProgressState(project_root="/tmp/test")
    subscriber = RecordingSubscriber()
    progress_state.subscribe(subscriber)

    ctx = DispatchContext(
        work=work,
        git=FakeGitAdapter(),
        review=FakeReviewAdapter(),
        runner=runner,
        progress_state=progress_state,
        config=ProjectConfig(),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id="run-progress",
    )

    await dispatch(ctx)

    group_opens = [e for e in subscriber.events if isinstance(e, GroupOpen)]
    group_closes = [e for e in subscriber.events if isinstance(e, GroupClose)]
    assert any("Agent output" in e.title for e in group_opens), (
        f"No 'Agent output' GroupOpen in {[e.title for e in group_opens]}"
    )
    assert len(group_closes) >= 1


@pytest.mark.asyncio
async def test_dispatch_stage_end_success_flag() -> None:
    """GIVEN a successful dispatch
    WHEN StageEnd is emitted
    THEN success=True.
    """
    event = PipelineEvent(key="35", trigger_stage=StageName.SPEC)
    work = FakeWorkAdapter(event=event, ticket_body="Build patient form")
    runner = FakeRunner(
        RunResult(
            success=True,
            output=_COMPLETE_OUTPUT,
            total_cost_usd=0.5,
            input_tokens=1000,
            output_tokens=2000,
            duration_ms=5000,
            num_turns=10,
        )
    )
    progress_state = ProgressState(project_root="/tmp/test")
    subscriber = RecordingSubscriber()
    progress_state.subscribe(subscriber)

    ctx = DispatchContext(
        work=work,
        git=FakeGitAdapter(),
        review=FakeReviewAdapter(),
        runner=runner,
        progress_state=progress_state,
        config=ProjectConfig(),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id="run-progress-ok",
    )

    await dispatch(ctx)

    end_events = [e for e in subscriber.events if isinstance(e, StageEnd)]
    assert len(end_events) == 1
    assert end_events[0].success is True
    assert end_events[0].error is None
