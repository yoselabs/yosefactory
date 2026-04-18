"""Tests for ProgressAdapter wiring in dispatch."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.config import ProjectConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult
from a2sdlc.pipeline.dispatch import DispatchContext, dispatch
from tests.fakes import (
    FakeGitAdapter,
    FakeProgressAdapter,
    FakeReviewAdapter,
    FakeRunner,
    FakeWorkAdapter,
)

_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'


@pytest.mark.asyncio
async def test_dispatch_calls_progress_adapter_on_agent_output() -> None:
    """GIVEN a dispatch that runs a stage successfully
    WHEN dispatch completes
    THEN progress.on_group_open / on_event / on_group_close were called
    for the agent-output block (replacing the previous ::group:: prints).
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
    progress = FakeProgressAdapter()
    ctx = DispatchContext(
        work=work,
        git=FakeGitAdapter(),
        review=FakeReviewAdapter(),
        runner=runner,
        progress=progress,
        config=ProjectConfig(),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id="run-progress",
    )

    await dispatch(ctx)

    assert any("Agent output" in title for title in progress.groups_open)
    assert any(event_type == "output" for event_type, _ in progress.events)
    assert progress.groups_closed >= 1
