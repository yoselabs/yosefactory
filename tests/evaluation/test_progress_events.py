"""Event taxonomy — concrete dataclasses + ProgressEvent union."""

from __future__ import annotations

from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    ProgressEvent,
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
