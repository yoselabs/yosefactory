"""N6 standalone-invocability contract test for SpecStage.

The architecture constraint (RFC-0001 N6): every handler must be
callable in isolation — given a fake ctx with all per-run fields
populated, ``execute()`` completes and returns a ``StageOutcome``
without any implicit dependency on dispatch's surrounding plumbing.

This test proves SpecStage carries no hidden coupling: no module-level
state, no reliance on dispatch() wrapping, no expectation of a real
telemetry session beyond the ``RunHandle`` passed on ctx.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from a2sdlc.config import load_stage_config
from a2sdlc.domain.models import StageName, StageStatus
from a2sdlc.domain.run_result import RunResult
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.effects.apply import apply as apply_effects
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.stages.spec import SpecStage
from tests.fakes import (
    FakeRunner,
    default_run_result,
    make_dispatch_context,
    populate_run_intent,
)


_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'


def _populate_per_run_state(ctx: Any, output: str = _COMPLETE_OUTPUT) -> RunIntent:
    """Mimic what dispatch() does before calling handler.execute.

    Runs preflight, builds pr_lifecycle + comment manager, loads stage
    config, and attaches a MagicMock RunHandle. Returns the pre for
    convenience.
    """
    pre = populate_run_intent(ctx)

    ctx.intent = pre
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.comment = CommentManager(ctx.work, pre.event.key)
    ctx.comment.start(pre.target_stage.value)
    ctx.pr_number = None
    ctx.stage_config = load_stage_config(pre.target_stage.value, ctx.config)
    ctx.run = MagicMock(name="RunHandle")
    # Silence the runner fixture — replace with a single COMPLETE result.
    ctx.runner = FakeRunner([default_run_result(output)])
    return pre


@pytest.mark.asyncio
async def test_spec_stage_execute_runs_standalone_and_returns_outcome() -> None:
    """N6: SpecStage().execute + effects() + interpreter round-trips standalone."""
    ctx, work, git, _review, _runner = make_dispatch_context(
        project_root=Path("/tmp/test_spec_stage")
    )
    _populate_per_run_state(ctx)

    stage = SpecStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert isinstance(outcome, StageOutcome)
    assert outcome.status == StageStatus.COMPLETE
    assert outcome.stats is not None
    # Happy path emits a state write + a stage comment finalized — now via
    # the interpreter, not direct adapter calls from execute().
    assert len(work.finalized_comments) == 1
    assert len(git.written_state) >= 1


@pytest.mark.asyncio
async def test_spec_stage_execute_failure_returns_blocked_outcome() -> None:
    """Runner failure → StageOutcome(blocked=True, error=...) + MarkBlocked effect."""
    ctx, work, *_ = make_dispatch_context(
        runner_results=[RunResult(success=False, error="timeout")],
        project_root=Path("/tmp/test_spec_stage_fail"),
    )
    _populate_per_run_state(ctx)
    ctx.runner = FakeRunner([RunResult(success=False, error="timeout")])

    stage = SpecStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status is None
    assert len(work.blocked) == 1


def test_spec_stage_preconditions_returns_none_in_p2() -> None:
    """P2: preconditions is a no-op; preflight still owns gating."""
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_spec_stage_pre"))
    assert SpecStage().preconditions(ctx) is None


def test_spec_stage_effects_is_empty_in_p2() -> None:
    """Empty outcome → empty effect list."""
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_spec_stage_eff"))
    outcome = StageOutcome(status=StageStatus.COMPLETE)
    assert SpecStage().effects(ctx, outcome) == []


@pytest.mark.asyncio
async def test_spec_stage_happy_path_emits_effects_without_calling_adapters() -> None:
    """P3 step 4: execute() is pure w.r.t. adapters; side effects live in effects().

    On the happy path, we expect the effect list to contain:
    - CommentFinalize (final comment body)
    - StateWrite (new TicketState)
    - CommitAndPush (artifacts commit)
    - SetCurrentStage (transition to IMPLEMENT)
    - LogMetric × 5 (tokens_in, tokens_out, cost_usd, turns, duration_ms)
    """
    from a2sdlc.domain.effects import (
        CommentFinalize,
        CommitAndPush,
        LogMetric,
        SetCurrentStage,
        StateWrite,
    )

    ctx, work, git, _review, _runner = make_dispatch_context(
        project_root=Path("/tmp/test_spec_stage_effects_happy")
    )
    _populate_per_run_state(ctx)

    stage = SpecStage()
    outcome = await stage.execute(ctx)
    effects = stage.effects(ctx, outcome)

    # execute() did not touch adapters directly — this is the "pure" guarantee.
    assert work.finalized_comments == []
    assert git.written_state == []
    assert work.label_history == []
    assert work.blocked == []

    # effects() carries the payload.
    types_ = [type(e) for e in effects]
    assert CommentFinalize in types_
    assert StateWrite in types_
    assert CommitAndPush in types_
    assert SetCurrentStage in types_
    assert types_.count(LogMetric) == 5


@pytest.mark.asyncio
async def test_spec_stage_questions_emits_mark_needs_input() -> None:
    """QUESTIONS status → next_stage is None → MarkNeedsInput effect emitted."""
    from a2sdlc.domain.effects import MarkNeedsInput, SetCurrentStage

    questions_output = '```a2sdlc\n{"status": "questions", "output": "Ambiguous"}\n```'
    ctx, work, *_ = make_dispatch_context(
        project_root=Path("/tmp/test_spec_stage_questions")
    )
    _populate_per_run_state(ctx, questions_output)

    stage = SpecStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status == StageStatus.QUESTIONS
    types_ = [type(e) for e in outcome.prepared_effects]
    assert MarkNeedsInput in types_
    assert SetCurrentStage not in types_
    assert work.needs_input == ["35"]


@pytest.mark.asyncio
async def test_spec_stage_failure_path_emits_blocked_effects() -> None:
    """Failure path emits CommentFinalize + CommitAndPush + MarkBlocked — no StateWrite."""
    from a2sdlc.domain.effects import (
        CommentFinalize,
        CommitAndPush,
        MarkBlocked,
        StateWrite,
    )

    ctx, work, *_ = make_dispatch_context(
        runner_results=[RunResult(success=False, error="timeout")],
        project_root=Path("/tmp/test_spec_stage_effects_fail"),
    )
    _populate_per_run_state(ctx)
    ctx.runner = FakeRunner([RunResult(success=False, error="timeout")])

    stage = SpecStage()
    outcome = await stage.execute(ctx)
    effects = stage.effects(ctx, outcome)

    # No direct adapter calls.
    assert work.blocked == []
    assert work.finalized_comments == []

    types_ = [type(e) for e in effects]
    assert CommentFinalize in types_
    assert CommitAndPush in types_
    assert MarkBlocked in types_
    assert StateWrite not in types_

    # The outcome still carries the blocked/error flags for dispatch's tuple
    # translation — step 9 removes this duplication after all handlers migrate.


def test_spec_stage_name_and_valid_statuses() -> None:
    stage = SpecStage()
    assert stage.name is StageName.SPEC
    assert stage.valid_statuses == frozenset(
        {StageStatus.COMPLETE, StageStatus.QUESTIONS}
    )
