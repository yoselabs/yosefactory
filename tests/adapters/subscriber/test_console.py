"""ConsoleSubscriber — three-rhythm renderer + legacy rich.Live API."""

from __future__ import annotations

import io

import pytest

from a2sdlc.adapters.subscriber.console import ConsoleSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import (
    Metrics,
    Milestone,
    ProgressState,
    RunEnd,
    StageEnd,
    StageStart,
    ToolEntry,
)
from a2sdlc.domain.stats import StageRunStats


def _metrics(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_cost_usd: float = 0.0,
    num_turns: int = 0,
    elapsed: float = 0.0,
) -> Metrics:
    return Metrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost_usd=total_cost_usd,
        num_turns=num_turns,
        elapsed=elapsed,
    )


# ── Plain-text three-rhythm renderer (new) ─────────────────────────


@pytest.mark.asyncio
async def test_stage_start_renders_starting_line() -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    out = buf.getvalue()
    assert "[SPEC]      starting (cycle 1)" in out


@pytest.mark.asyncio
async def test_stage_start_increments_cycle_per_stage() -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(
        StageStart(stage=StageName.IMPLEMENT, session_id="s2", started_at=0.0)
    )
    await sub.handle(
        StageStart(stage=StageName.IMPLEMENT, session_id="s3", started_at=0.0)
    )
    out = buf.getvalue()
    assert "[SPEC]      starting (cycle 1)" in out
    assert "[IMPLEMENT] starting (cycle 1)" in out
    assert "[IMPLEMENT] starting (cycle 2)" in out


@pytest.mark.asyncio
async def test_mid_stage_event_log_lines(tmp_path) -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(Milestone(timestamp=1.0, label="brainstorming invoked"))
    await sub.handle(ToolEntry(timestamp=2.0, name="Read", target="foo.py"))
    out = buf.getvalue()
    assert "[SPEC]" in out
    assert "brainstorming invoked" in out
    assert "Read" in out
    assert "foo.py" in out


@pytest.mark.asyncio
async def test_stage_end_emits_output_block_and_stats(tmp_path) -> None:
    artifact = tmp_path / "spec.md"
    artifact.write_text("hello world\n")
    final = _metrics(
        input_tokens=12_400,
        output_tokens=3_100,
        num_turns=4,
        total_cost_usd=0.082,
        elapsed=18.3,
    )
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(
        StageEnd(
            stage=StageName.SPEC,
            success=True,
            error=None,
            final_metrics=final,
            artifact_path=artifact,
        )
    )
    out = buf.getvalue()
    assert "===== a2sdlc:stage-output BEGIN =====" in out
    assert "hello world" in out
    assert "===== a2sdlc:stage-output END =====" in out
    assert "18s · 4 turns · 12.4k in / 3.1k out · $0.08" in out


@pytest.mark.asyncio
async def test_stage_end_no_artifact_skips_output_block(tmp_path) -> None:
    final = _metrics(
        input_tokens=1000,
        output_tokens=500,
        num_turns=1,
        total_cost_usd=0.01,
        elapsed=5.0,
    )
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(
        StageEnd(
            stage=StageName.SPEC,
            success=True,
            error=None,
            final_metrics=final,
            artifact_path=None,
        )
    )
    out = buf.getvalue()
    assert "stage-output BEGIN" not in out
    assert "5s" in out


@pytest.mark.asyncio
async def test_run_end_success_renders_totals() -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(
        RunEnd(
            workflow_id="a2sdlc/auto/x/20260430-142208-a3f019",
            success=True,
            error=None,
            aggregate_stats=StageRunStats(
                cost_usd=0.79,
                tokens_in=107_100,
                tokens_out=26_200,
                duration_ms=317_000,
                num_turns=23,
            ),
            total_cycles={
                StageName.SPEC: 1,
                StageName.IMPLEMENT: 2,
                StageName.REVIEW: 2,
            },
        )
    )
    out = buf.getvalue()
    assert "totals: 5m 17s · 23 turns · 107.1k in / 26.2k out · $0.79" in out
    assert "totals (failed):" not in out


@pytest.mark.asyncio
async def test_run_end_failure_renders_failed_totals() -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(
        RunEnd(
            workflow_id="x",
            success=False,
            error="push failed",
            aggregate_stats=StageRunStats(),
            total_cycles={},
        )
    )
    out = buf.getvalue()
    assert "totals (failed):" in out
    assert "push failed" in out


# ── Coverage for defensive + transition branches ───────────────────


@pytest.mark.asyncio
async def test_group_open_close_and_metrics_in_plain_mode() -> None:
    from a2sdlc.domain.progress import GroupClose, GroupOpen

    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(GroupOpen(title="reading specs"))
    await sub.handle(GroupClose())
    # Per-tick Metrics is a no-op in plain mode (only StageEnd renders stats).
    await sub.handle(
        Metrics(
            input_tokens=1,
            output_tokens=1,
            total_cost_usd=0.0,
            num_turns=1,
            elapsed=1.0,
        )
    )
    out = buf.getvalue()
    assert "reading specs" in out
    assert "[SPEC]" in out
    assert "end" in out


@pytest.mark.asyncio
async def test_orphan_milestone_uses_blank_tag() -> None:
    """Milestone before any StageStart still renders (with blank tag)."""
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(Milestone(timestamp=0.0, label="orphan"))
    out = buf.getvalue()
    assert "orphan" in out


@pytest.mark.asyncio
async def test_stage_end_none_metrics_renders_dashes(tmp_path) -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    # final_metrics is typed Metrics, but the renderer must defend against
    # None on terminal-error paths where dispatch couldn't snapshot stats.
    end = StageEnd(
        stage=StageName.SPEC,
        success=True,
        error=None,
        final_metrics=Metrics(0, 0, 0.0, 0, 0.0),
        artifact_path=None,
    )
    object.__setattr__(end, "final_metrics", None)
    await sub.handle(end)
    out = buf.getvalue()
    assert "- · - turns · - in / - out · -" in out


@pytest.mark.asyncio
async def test_stage_end_artifact_oserror_swallowed(tmp_path, monkeypatch) -> None:
    """If reading the artifact raises OSError, the renderer falls through to
    the stats line without crashing."""
    artifact = tmp_path / "spec.md"
    artifact.write_text("hello\n")

    real_read = type(artifact).read_text

    def boom(self, *a, **kw):  # type: ignore[no-untyped-def]
        if self == artifact:
            raise OSError("disk gone")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(type(artifact), "read_text", boom)

    final = _metrics(elapsed=1.0, num_turns=1)
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(
        StageEnd(
            stage=StageName.SPEC,
            success=True,
            error=None,
            final_metrics=final,
            artifact_path=artifact,
        )
    )
    out = buf.getvalue()
    assert "stage-output BEGIN" not in out
    assert "1s" in out


@pytest.mark.asyncio
async def test_review_success_renders_approved_transition() -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(
        StageStart(stage=StageName.REVIEW, session_id="r1", started_at=0.0)
    )
    await sub.handle(
        StageEnd(
            stage=StageName.REVIEW,
            success=True,
            error=None,
            final_metrics=_metrics(elapsed=2.0, num_turns=1),
            artifact_path=None,
        )
    )
    assert "approved" in buf.getvalue()


@pytest.mark.asyncio
async def test_review_failure_renders_handover_transition() -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(
        StageStart(stage=StageName.REVIEW, session_id="r1", started_at=0.0)
    )
    await sub.handle(
        StageEnd(
            stage=StageName.REVIEW,
            success=False,
            error="changes requested",
            final_metrics=_metrics(elapsed=2.0),
            artifact_path=None,
        )
    )
    assert "handover → IMPLEMENT" in buf.getvalue()


@pytest.mark.asyncio
async def test_non_review_failure_renders_failed_transition() -> None:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(
        StageEnd(
            stage=StageName.SPEC,
            success=False,
            error="boom",
            final_metrics=_metrics(elapsed=1.0),
            artifact_path=None,
        )
    )
    assert "failed" in buf.getvalue()


@pytest.mark.asyncio
async def test_run_end_in_legacy_mode_is_noop() -> None:
    """RunEnd received by a state-bound (legacy) subscriber is silently
    ignored — the pipeline-level totals aren't part of the rich-pane UX."""
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    await sub.handle(
        RunEnd(
            workflow_id="x",
            success=True,
            error=None,
            aggregate_stats=StageRunStats(),
            total_cycles={},
        )
    )
    # No stream, no exception.


def test_render_status_bar_without_state_returns_empty() -> None:
    """Plain-mode subscribers should still answer render_status_bar safely."""
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    assert sub.render_status_bar() == ""


# ── Legacy rich.Live mode (state-bound) ────────────────────────────


@pytest.mark.asyncio
async def test_metrics_event_updates_status_bar_counters() -> None:
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    state.subscribe(sub)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
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
    assert "7" in bar


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
    assert sub._live is None


@pytest.mark.asyncio
async def test_legacy_group_open_close_and_milestone_refresh_recent_events() -> None:
    """Legacy rich.Live mode appends GroupOpen/GroupClose/Milestone to recent_events."""
    from a2sdlc.domain.progress import GroupClose, GroupOpen

    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(GroupOpen(title="grouping"))
    await sub.handle(GroupClose())
    await sub.handle(Milestone(timestamp=0.0, label="hit"))
    rendered = "\n".join(sub.recent_events)
    assert "grouping" in rendered
    assert "end" in rendered
    assert "hit" in rendered


@pytest.mark.asyncio
async def test_run_end_flush_swallows_exception() -> None:
    """If the underlying stream's flush() raises, RunEnd handler must not crash."""

    class BoomStream(io.StringIO):
        def flush(self) -> None:  # type: ignore[override]
            raise OSError("pipe closed")

    buf = BoomStream()
    sub = ConsoleSubscriber(stream=buf)
    await sub.handle(
        RunEnd(
            workflow_id="x",
            success=True,
            error=None,
            aggregate_stats=StageRunStats(),
            total_cycles={},
        )
    )
    assert "totals:" in buf.getvalue()
