"""Closed-ticket dispatch path.

Split from ``test_dispatch.py`` to keep that file under the 500-line
cap. Exercises the composition-root branch that handles ``is_closed``
events without running a stage (P4 step 5 moved this check from
``run_preflight`` into ``dispatch.dispatch`` itself).
"""

from __future__ import annotations

import pytest

from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.pipeline.dispatch import dispatch
from tests.fakes import FakeWorkAdapter, default_run_result, make_dispatch_context


@pytest.mark.asyncio
async def test_ticket_closed_marks_done_without_running_stage() -> None:
    ctx, *_ = make_dispatch_context(
        event=PipelineEvent(key="15", trigger_stage=StageName.SPEC),
        ticket_body="",
        runner_results=[default_run_result("")],
        run_id="run-closed",
    )
    ctx.work = FakeWorkAdapter(
        event=PipelineEvent(key="15", is_closed=True),
        ticket_body="",
    )
    result = await dispatch(ctx)
    assert result.stage == StageName.MERGE
    assert result.error == "ticket_closed"
    assert ("15", "stage:done") in ctx.work.label_history
    assert ctx.work.created_comments == []
