"""GhActionsLogSubscriber — emits ::group::/::endgroup:: + plain lines."""

from __future__ import annotations

import pytest

from a2sdlc.adapters.gh_actions_subscriber import GhActionsLogSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    StageEnd,
    StageStart,
    ToolEntry,
)


@pytest.mark.asyncio
async def test_stage_start_opens_workflow_group(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    out = capsys.readouterr().out
    assert "::group::Stage spec (session sid)" in out


@pytest.mark.asyncio
async def test_stage_end_closes_group_with_status(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    capsys.readouterr()  # drain
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(
        StageEnd(stage=StageName.SPEC, success=True, error=None, final_metrics=final)
    )
    out = capsys.readouterr().out
    assert "Stage spec end: OK" in out
    assert "::endgroup::" in out


@pytest.mark.asyncio
async def test_tool_entry_emits_grouped_block(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(ToolEntry(timestamp=0.1, name="Read", target="foo.py"))
    out = capsys.readouterr().out
    assert "::group::Tool: Read" in out
    assert "foo.py" in out
    assert "::endgroup::" in out


@pytest.mark.asyncio
async def test_group_open_close_round_trip(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(GroupOpen(title="Agent output (1234 chars)"))
    await sub.handle(GroupClose())
    out = capsys.readouterr().out
    assert "::group::Agent output (1234 chars)" in out
    assert "::endgroup::" in out
