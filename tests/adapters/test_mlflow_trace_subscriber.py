"""MlflowTraceSubscriber — emits MLflow spans for stages + tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from a2sdlc.adapters.mlflow_trace_subscriber import MlflowTraceSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    StageEnd,
    StageStart,
    ToolEntry,
)


@dataclass
class FakeSpan:
    """Records every call made against the span."""

    name: str
    parent: "FakeSpan | None"
    attributes: dict[str, object] = field(default_factory=dict)
    ended: bool = False
    single_attributes: dict[str, object] = field(default_factory=dict)

    def set_attributes(self, values: dict[str, object]) -> None:
        self.attributes.update(values)

    def set_attribute(self, key: str, value: object) -> None:
        self.single_attributes[key] = value
        self.attributes[key] = value

    def end(self) -> None:
        self.ended = True


@dataclass
class FakeMlflow:
    """Mock of ``mlflow.start_span_no_context`` that records spans created."""

    spans: list[FakeSpan] = field(default_factory=list)

    def start_span_no_context(
        self,
        name: str,
        parent_span: FakeSpan | None = None,
        attributes: dict[str, object] | None = None,
    ) -> FakeSpan:
        span = FakeSpan(
            name=name,
            parent=parent_span,
            attributes=dict(attributes or {}),
        )
        self.spans.append(span)
        return span


@pytest.fixture
def fake_mlflow(monkeypatch) -> FakeMlflow:
    fake = FakeMlflow()
    monkeypatch.setattr(
        "a2sdlc.adapters.mlflow_trace_subscriber.mlflow.start_span_no_context",
        fake.start_span_no_context,
    )
    return fake


@pytest.mark.asyncio
async def test_stage_start_opens_root_span(fake_mlflow) -> None:
    """GIVEN a StageStart event
    WHEN the subscriber handles it
    THEN a root span named 'stage:<name>' is opened with session_id attribute."""
    sub = MlflowTraceSubscriber()
    await sub.handle(
        StageStart(stage=StageName.SPEC, session_id="sid-1", started_at=0.0)
    )

    assert len(fake_mlflow.spans) == 1
    span = fake_mlflow.spans[0]
    assert span.name == "stage:spec"
    assert span.parent is None
    assert span.attributes["session_id"] == "sid-1"
    assert not span.ended


@pytest.mark.asyncio
async def test_tool_entry_opens_child_span_parented_on_stage(fake_mlflow) -> None:
    """GIVEN a stage has started
    WHEN a ToolEntry arrives
    THEN a child span 'tool:<name>' is opened with the stage span as parent."""
    sub = MlflowTraceSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(ToolEntry(timestamp=0.5, name="Read", target="foo.py"))

    assert len(fake_mlflow.spans) == 2
    stage_span, tool_span = fake_mlflow.spans
    assert tool_span.name == "tool:Read"
    assert tool_span.parent is stage_span
    assert tool_span.attributes["target"] == "foo.py"
    assert tool_span.attributes["elapsed"] == 0.5


@pytest.mark.asyncio
async def test_second_tool_closes_first(fake_mlflow) -> None:
    """GIVEN a tool span is active
    WHEN a second ToolEntry arrives
    THEN the first tool span is closed and a new one opens."""
    sub = MlflowTraceSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(ToolEntry(timestamp=0.1, name="Read", target="a.py"))
    await sub.handle(ToolEntry(timestamp=0.2, name="Bash", target="`ls`"))

    _, first_tool, second_tool = fake_mlflow.spans
    assert first_tool.ended is True
    assert second_tool.ended is False
    assert second_tool.name == "tool:Bash"


@pytest.mark.asyncio
async def test_metrics_update_stage_attributes(fake_mlflow) -> None:
    """GIVEN a stage span is open
    WHEN Metrics arrives
    THEN cumulative counters are written as attributes on the stage span."""
    sub = MlflowTraceSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(
        Metrics(
            input_tokens=1000,
            output_tokens=200,
            total_cost_usd=0.05,
            num_turns=3,
            elapsed=1.2,
        )
    )

    stage_span = fake_mlflow.spans[0]
    assert stage_span.attributes["tokens_in"] == 1000
    assert stage_span.attributes["tokens_out"] == 200
    assert stage_span.attributes["cost_usd"] == 0.05
    assert stage_span.attributes["num_turns"] == 3


@pytest.mark.asyncio
async def test_milestone_adds_attribute_to_stage_span(fake_mlflow) -> None:
    sub = MlflowTraceSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(Milestone(timestamp=0.9, label="brainstorming invoked"))

    stage_span = fake_mlflow.spans[0]
    keys = [k for k in stage_span.attributes if k.startswith("milestone:")]
    assert len(keys) == 1
    assert stage_span.attributes[keys[0]] == "brainstorming invoked"


@pytest.mark.asyncio
async def test_group_events_are_ignored(fake_mlflow) -> None:
    sub = MlflowTraceSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    before = len(fake_mlflow.spans)
    await sub.handle(GroupOpen(title="ignored"))
    await sub.handle(GroupClose())
    assert len(fake_mlflow.spans) == before


@pytest.mark.asyncio
async def test_stage_end_closes_tool_and_stage_spans(fake_mlflow) -> None:
    """GIVEN a tool span is active when the stage ends
    WHEN StageEnd arrives
    THEN both the tool span and the stage span are closed; final metrics recorded."""
    sub = MlflowTraceSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(ToolEntry(timestamp=0.1, name="Read", target="a.py"))

    final = Metrics(
        input_tokens=500,
        output_tokens=100,
        total_cost_usd=0.02,
        num_turns=2,
        elapsed=3.0,
    )
    await sub.handle(
        StageEnd(stage=StageName.SPEC, success=True, error=None, final_metrics=final)
    )

    stage_span, tool_span = fake_mlflow.spans
    assert tool_span.ended is True
    assert stage_span.ended is True
    assert stage_span.attributes["success"] is True
    assert stage_span.attributes["error"] == ""
    assert stage_span.attributes["final_cost_usd"] == 0.02
    assert stage_span.attributes["final_tokens_in"] == 500
    assert stage_span.attributes["final_tokens_out"] == 100
    assert stage_span.attributes["final_num_turns"] == 2


@pytest.mark.asyncio
async def test_stage_end_records_error_on_failure(fake_mlflow) -> None:
    sub = MlflowTraceSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(
        StageEnd(
            stage=StageName.SPEC,
            success=False,
            error="runner crashed",
            final_metrics=final,
        )
    )

    stage_span = fake_mlflow.spans[0]
    assert stage_span.ended is True
    assert stage_span.attributes["success"] is False
    assert stage_span.attributes["error"] == "runner crashed"


@pytest.mark.asyncio
async def test_metrics_without_stage_is_safe(fake_mlflow) -> None:
    """Metrics emitted before StageStart (shouldn't happen, but guard) is a no-op."""
    sub = MlflowTraceSubscriber()
    await sub.handle(Metrics(1, 1, 0.0, 1, 0.0))
    assert fake_mlflow.spans == []


@pytest.mark.asyncio
async def test_two_consecutive_stages_each_get_own_root(fake_mlflow) -> None:
    """GIVEN two stages run in sequence on the same subscriber instance
    WHEN each stage fires StageStart/StageEnd
    THEN each stage opens a distinct root span."""
    sub = MlflowTraceSubscriber()
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(
        StageEnd(stage=StageName.SPEC, success=True, error=None, final_metrics=final)
    )
    await sub.handle(
        StageStart(stage=StageName.IMPLEMENT, session_id="sid", started_at=1.0)
    )
    await sub.handle(
        StageEnd(
            stage=StageName.IMPLEMENT, success=True, error=None, final_metrics=final
        )
    )

    assert len(fake_mlflow.spans) == 2
    assert fake_mlflow.spans[0].name == "stage:spec"
    assert fake_mlflow.spans[1].name == "stage:implement"
    assert all(s.parent is None for s in fake_mlflow.spans)
    assert all(s.ended for s in fake_mlflow.spans)
