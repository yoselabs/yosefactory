"""Event taxonomy — concrete dataclasses + ProgressEvent union."""

from __future__ import annotations

import pytest

from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    ProgressEvent,
    ProgressState,
    StageEnd,
    StageStart,
    ToolEntry,
)


def test_stage_start_carries_stage_session_started_at() -> None:
    evt = StageStart(stage=StageName.SPEC, session_id="abc", started_at=12.5)
    assert evt.stage == StageName.SPEC
    assert evt.session_id == "abc"
    assert evt.started_at == 12.5


def test_metrics_carries_token_cost_turns_elapsed() -> None:
    m = Metrics(
        input_tokens=1, output_tokens=2, total_cost_usd=0.5, num_turns=3, elapsed=4.0
    )
    assert m.input_tokens == 1
    assert m.output_tokens == 2
    assert m.total_cost_usd == 0.5
    assert m.num_turns == 3
    assert m.elapsed == 4.0


def test_stage_end_carries_final_metrics() -> None:
    final = Metrics(1, 2, 0.5, 3, 4.0)
    evt = StageEnd(
        stage=StageName.IMPLEMENT, success=True, error=None, final_metrics=final
    )
    assert evt.success is True
    assert evt.error is None
    assert evt.final_metrics is final


def test_progressevent_union_includes_all_event_types() -> None:
    sample: list[ProgressEvent] = [
        StageStart(stage=StageName.SPEC, session_id="x", started_at=0.0),
        ToolEntry(timestamp=0.1, name="Read", target="foo.py"),
        GroupOpen(title="t"),
        GroupClose(),
        Metrics(0, 0, 0.0, 0, 0.0),
        Milestone(timestamp=1.0, label="x"),
        StageEnd(
            stage=StageName.SPEC,
            success=True,
            error=None,
            final_metrics=Metrics(0, 0, 0.0, 0, 0.0),
        ),
    ]
    assert len(sample) == 7


# ── Bus tests ─────────────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self) -> None:
        self.events: list = []

    async def handle(self, event) -> None:
        self.events.append(event)


def _make_state() -> ProgressState:
    return ProgressState(project_root="/tmp/test")


@pytest.mark.asyncio
async def test_stage_start_emits_StageStart_and_resets_state() -> None:
    state = _make_state()
    state.tool_log.append(ToolEntry(timestamp=0.0, name="x", target="y"))
    state.input_tokens = 99
    rec = _Recorder()
    state.subscribe(rec)

    await state.stage_start(
        StageName.SPEC,
        "sid",
        model="claude-x",
        max_turns=10,
        context_window=200_000,
        branch="b",
    )

    assert state.tool_log == []
    assert state.input_tokens == 0
    assert state.model == "claude-x"
    assert state.max_turns == 10
    assert state.context_window == 200_000
    assert state.branch == "b"
    assert len(rec.events) == 1
    assert isinstance(rec.events[0], StageStart)
    assert rec.events[0].stage == StageName.SPEC
    assert rec.events[0].session_id == "sid"


@pytest.mark.asyncio
async def test_add_tool_call_appends_and_emits_ToolEntry() -> None:
    state = _make_state()
    rec = _Recorder()
    state.subscribe(rec)
    await state.stage_start(
        StageName.SPEC, "sid", model="m", max_turns=1, context_window=1, branch="b"
    )
    rec.events.clear()

    await state.add_tool_call("Read", "foo.py")

    assert len(state.tool_log) == 1
    assert state.tool_log[0].name == "Read"
    assert state.tool_log[0].target == "foo.py"
    assert len(rec.events) == 1
    assert rec.events[0] is state.tool_log[0]  # same reference, not a copy


@pytest.mark.asyncio
async def test_update_metrics_writes_state_and_emits_Metrics() -> None:
    state = _make_state()
    rec = _Recorder()
    state.subscribe(rec)
    await state.stage_start(
        StageName.SPEC, "sid", model="m", max_turns=1, context_window=1, branch="b"
    )
    rec.events.clear()

    await state.update_metrics(tin=10, tout=20, cost=0.05, turns=2)

    assert state.input_tokens == 10
    assert state.output_tokens == 20
    assert state.total_cost_usd == 0.05
    assert state.num_turns == 2
    assert len(rec.events) == 1
    assert isinstance(rec.events[0], Metrics)
    assert rec.events[0].input_tokens == 10
    assert rec.events[0].num_turns == 2


@pytest.mark.asyncio
async def test_subscribers_receive_events_in_registration_order() -> None:
    state = _make_state()
    a, b, c = _Recorder(), _Recorder(), _Recorder()
    state.subscribe(a)
    state.subscribe(b)
    state.subscribe(c)

    await state.stage_start(
        StageName.SPEC, "sid", model="m", max_turns=1, context_window=1, branch="b"
    )

    assert len(a.events) == len(b.events) == len(c.events) == 1


@pytest.mark.asyncio
async def test_failing_subscriber_is_skipped_for_remainder_of_stage() -> None:
    class _Boom:
        async def handle(self, event) -> None:
            raise RuntimeError("boom")

    state = _make_state()
    boom = _Boom()
    good = _Recorder()
    state.subscribe(boom)
    state.subscribe(good)

    await state.stage_start(
        StageName.SPEC, "sid", model="m", max_turns=1, context_window=1, branch="b"
    )
    await state.add_tool_call("Read", "x")

    assert len(good.events) == 2  # both events received despite boom failing


@pytest.mark.asyncio
async def test_failed_set_clears_on_next_stage_start() -> None:
    class _BoomOnce:
        def __init__(self) -> None:
            self.calls = 0

        async def handle(self, event) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")

    state = _make_state()
    sub = _BoomOnce()
    state.subscribe(sub)

    await state.stage_start(
        StageName.SPEC, "s1", model="m", max_turns=1, context_window=1, branch="b"
    )
    # Subscriber failed once; now in _failed for the rest of this stage.
    await state.add_tool_call("x", "y")
    assert sub.calls == 1  # not invoked second time

    await state.stage_start(
        StageName.IMPLEMENT, "s2", model="m", max_turns=1, context_window=1, branch="b"
    )
    # _failed cleared; subscriber invoked again.
    assert sub.calls == 2  # called for StageStart of IMPLEMENT


@pytest.mark.asyncio
async def test_snapshot_metrics_returns_current_counters_without_emitting() -> None:
    state = _make_state()
    rec = _Recorder()
    state.subscribe(rec)
    await state.stage_start(
        StageName.SPEC, "sid", model="m", max_turns=1, context_window=1, branch="b"
    )
    await state.update_metrics(tin=5, tout=7, cost=0.1, turns=1)
    rec.events.clear()

    snap = state.snapshot_metrics()

    assert isinstance(snap, Metrics)
    assert snap.input_tokens == 5
    assert snap.output_tokens == 7
    assert snap.total_cost_usd == 0.1
    assert snap.num_turns == 1
    assert rec.events == []  # no emit
