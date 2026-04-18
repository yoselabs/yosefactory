"""Tests for ProgressState wiring in dispatch."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.config import ProjectConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult
from a2sdlc.evaluation.progress import (
    Metrics,
    ProgressState,
    StageEnd,
)
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


@pytest.mark.asyncio
async def test_stage_end_follows_final_metrics() -> None:
    """GIVEN a runner that emits Metrics events during a stage
    WHEN dispatch emits StageEnd at the close
    THEN StageEnd appears AFTER the final Metrics event in the stream.

    Locks the spec §3.6 terminal-state guarantee: subscribers can rely on
    StageEnd being the last word; intermediate Metrics events that may have
    been throttled get superseded by the StageEnd's final_metrics payload.
    """
    from a2sdlc.config import StageConfig  # noqa: PLC0415

    event = PipelineEvent(key="42", trigger_stage=StageName.SPEC)
    work = FakeWorkAdapter(event=event, ticket_body="Build patient form")

    # Subclass FakeRunner to mutate the shared progress_state so it emits
    # at least one Metrics event during the stage.
    class _MetricsEmittingRunner(FakeRunner):
        async def run(  # type: ignore[override]
            self,
            user_prompt: str,
            system_prompt: str,
            config: StageConfig,
            ticket_key: str,
            stage: StageName,
            project_root: str,
            progress_state: ProgressState,
            is_resume: bool = False,
            branch: str = "",
        ) -> RunResult:
            await progress_state.update_metrics(tin=100, tout=200, cost=0.1, turns=1)
            return RunResult(
                success=True,
                output=_COMPLETE_OUTPUT,
                total_cost_usd=0.5,
                input_tokens=100,
                output_tokens=200,
                duration_ms=5000,
                num_turns=1,
            )

    progress_state = ProgressState(project_root="/tmp/test")
    runner = _MetricsEmittingRunner(RunResult(success=True))

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
        run_id="run-ordering",
    )

    await dispatch(ctx)

    metrics_indices = [
        i for i, e in enumerate(subscriber.events) if isinstance(e, Metrics)
    ]
    end_indices = [
        i for i, e in enumerate(subscriber.events) if isinstance(e, StageEnd)
    ]
    assert metrics_indices, f"no Metrics event emitted in {subscriber.events}"
    assert end_indices, f"no StageEnd event emitted in {subscriber.events}"
    assert metrics_indices[-1] < end_indices[-1], (
        f"StageEnd at {end_indices[-1]} must follow final Metrics at "
        f"{metrics_indices[-1]}; full sequence: {[type(e).__name__ for e in subscriber.events]}"
    )
