"""L1 tests for ``pipeline.middleware.idempotency.with_idempotency``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from a2sdlc.domain.models import StageName, TicketState
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.middleware.idempotency import with_idempotency
from tests.fakes import make_dispatch_context, populate_run_intent


def _ctx_and_intent(run_id: str | None = "run-1") -> tuple[RunContext, RunIntent]:
    ctx, *_ = make_dispatch_context(
        run_id=run_id, project_root=Path("/tmp/test_with_idempotency")
    )
    intent = populate_run_intent(ctx)
    ctx.intent = intent
    return ctx, intent


@pytest.mark.asyncio
async def test_passthrough_when_run_id_is_fresh() -> None:
    ctx, intent = _ctx_and_intent(run_id="fresh-run")
    called = False

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        nonlocal called
        called = True
        return DispatchResult(stage=intent.target_stage)

    result = await with_idempotency(fake_next)(ctx, intent)
    assert called is True
    assert result.error is None


@pytest.mark.asyncio
async def test_short_circuits_on_duplicate_run_id() -> None:
    ctx, intent = _ctx_and_intent(run_id="dup-run")
    # Pre-seed the state with this run_id so check_idempotency → True.
    intent.state_mgr.write_state(
        TicketState(
            stage=StageName.SPEC,
            branch=intent.branch,
            stage_run_id="dup-run",
            last_updated="2026-04-23T00:00:00Z",
        )
    )

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        raise AssertionError("next_ must not run on duplicate")

    result = await with_idempotency(fake_next)(ctx, intent)
    assert result.error == "duplicate_run_id"
    assert result.stage is intent.target_stage


@pytest.mark.asyncio
async def test_none_run_id_passes_through() -> None:
    ctx, intent = _ctx_and_intent(run_id=None)
    called = False

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        nonlocal called
        called = True
        return DispatchResult(stage=intent.target_stage)

    await with_idempotency(fake_next)(ctx, intent)
    assert called is True
