"""L2 composition test — idempotency short-circuits before telemetry runs.

Proves the middleware ordering invariant: on a duplicate run_id, the
telemetry session must not open. If telemetry wrapped idempotency,
dupe replays would leave orphan MLflow runs + progress envelopes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from a2sdlc.config import load_stage_config
from a2sdlc.domain.models import StageName, TicketState
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.middleware.idempotency import with_idempotency
from a2sdlc.middleware.telemetry import with_telemetry
from tests.fakes import make_dispatch_context, populate_run_intent


@pytest.mark.asyncio
async def test_duplicate_run_id_never_opens_telemetry_session() -> None:
    ctx, *_ = make_dispatch_context(
        run_id="dup-run", project_root=Path("/tmp/test_comp_dup")
    )
    intent = populate_run_intent(ctx)
    ctx.intent = intent
    ctx.stage_config = load_stage_config(intent.target_stage.value, ctx.config)
    intent.state_mgr.write_state(
        TicketState(
            stage=StageName.SPEC,
            branch=intent.branch,
            stage_run_id="dup-run",
            last_updated="2026-04-23T00:00:00Z",
        )
    )

    events: list[str] = []

    class Recorder:
        async def handle(self, event: Any) -> None:
            events.append(type(event).__name__)

    ctx.progress_state.subscribe(Recorder())

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        raise AssertionError("run_stage must not execute on duplicate run_id")

    stack = with_idempotency(with_telemetry(fake_next))
    result = await stack(ctx, intent)
    assert result.error == "duplicate_run_id"
    # Telemetry envelope never fired — the inner layer was short-circuited.
    assert "StageStart" not in events
    assert "StageEnd" not in events
