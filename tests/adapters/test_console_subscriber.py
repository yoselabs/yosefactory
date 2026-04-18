"""ConsoleSubscriber — renders events into rich.Live status bar + scroll."""

from __future__ import annotations

import pytest

from a2sdlc.adapters.subscriber.console import ConsoleSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    Metrics,
    ProgressState,
    StageEnd,
    StageStart,
    ToolEntry,
)


@pytest.mark.asyncio
async def test_metrics_event_updates_status_bar_counters() -> None:
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    state.subscribe(sub)  # subscribe is sync; returns None.
    # Bypass actual rich.Live by accessing the rendered string directly.
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    # Set state directly so the status-bar reader sees the values.
    state.input_tokens = 1234
    state.output_tokens = 5678
    state.total_cost_usd = 0.42
    state.num_turns = 7
    await sub.handle(
        Metrics(
            input_tokens=1234,
            output_tokens=5678,
            total_cost_usd=0.42,
            num_turns=7,
            elapsed=10.0,
        )
    )
    bar = sub.render_status_bar()
    assert "1234" in bar
    assert "5678" in bar
    assert "0.42" in bar
    assert "7" in bar  # num_turns


@pytest.mark.asyncio
async def test_tool_entry_event_appends_to_recent_events() -> None:
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(ToolEntry(timestamp=0.1, name="Read", target="foo.py"))
    rendered = "\n".join(sub.recent_events)
    assert "Read" in rendered
    assert "foo.py" in rendered


@pytest.mark.asyncio
async def test_stage_end_closes_live_render() -> None:
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(
        StageEnd(stage=StageName.SPEC, success=True, error=None, final_metrics=final)
    )
    assert sub._live is None  # live render closed
