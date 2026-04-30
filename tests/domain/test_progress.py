"""StageEnd.artifact_path + RunEnd event."""

from __future__ import annotations

from pathlib import Path

from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import Metrics, RunEnd, StageEnd
from a2sdlc.domain.stats import StageRunStats


def _metrics() -> Metrics:
    return Metrics(
        input_tokens=0,
        output_tokens=0,
        total_cost_usd=0.0,
        num_turns=0,
        elapsed=0.0,
    )


def test_stage_end_artifact_path_default_none() -> None:
    e = StageEnd(
        stage=StageName.SPEC,
        success=True,
        error=None,
        final_metrics=_metrics(),
    )
    assert e.artifact_path is None


def test_stage_end_carries_artifact_path() -> None:
    e = StageEnd(
        stage=StageName.SPEC,
        success=True,
        error=None,
        final_metrics=_metrics(),
        artifact_path=Path("/tmp/spec.md"),
    )
    assert e.artifact_path == Path("/tmp/spec.md")


def test_run_end_dataclass_shape() -> None:
    e = RunEnd(
        workflow_id="a2sdlc/auto/x/20260430-142208-a3f019",
        success=True,
        error=None,
        aggregate_stats=StageRunStats(),
        total_cycles={
            StageName.SPEC: 1,
            StageName.IMPLEMENT: 2,
            StageName.REVIEW: 2,
        },
    )
    assert e.workflow_id == "a2sdlc/auto/x/20260430-142208-a3f019"
    assert e.success is True
    assert e.total_cycles[StageName.IMPLEMENT] == 2
