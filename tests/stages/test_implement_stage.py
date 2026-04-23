"""N6 standalone-invocability contract test for ImplementStage.

Mirrors ``test_spec_stage.py`` — proves ``ImplementStage`` carries no
hidden dispatch coupling: given a populated ctx, ``execute()`` returns
a ``StageOutcome`` in isolation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from a2sdlc.config import load_stage_config
from a2sdlc.domain.models import StageName, StageStatus
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.run_result import RunResult
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.pipeline.effects_apply import apply as apply_effects
from a2sdlc.pipeline.preflight import PreflightOutcome, run_preflight
from a2sdlc.stages.implement import ImplementStage
from tests.fakes import FakeRunner, default_run_result, make_dispatch_context


_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'


def _populate_per_run_state(
    ctx: Any, output: str = _COMPLETE_OUTPUT
) -> PreflightOutcome:
    pre = run_preflight(ctx)
    assert isinstance(pre, PreflightOutcome), f"preflight short-circuited: {pre!r}"
    ctx.pre = pre
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.comment = CommentManager(ctx.work, pre.event.key)
    ctx.comment.start(pre.target_stage.value)
    ctx.pr_number = 1
    ctx.stage_config = load_stage_config(pre.target_stage.value, ctx.config)
    ctx.run = MagicMock(name="RunHandle")
    ctx.runner = FakeRunner([default_run_result(output)])
    return pre


def _implement_ctx(**kwargs: Any) -> Any:
    event = PipelineEvent(key="35", trigger_stage=StageName.IMPLEMENT)
    return make_dispatch_context(event=event, **kwargs)


@pytest.mark.asyncio
async def test_implement_stage_execute_runs_standalone_and_returns_outcome() -> None:
    """N6: ImplementStage().execute + effects() + interpreter round-trips standalone."""
    ctx, work, git, _review, _runner = _implement_ctx(
        project_root=Path("/tmp/test_implement_stage")
    )
    _populate_per_run_state(ctx)

    stage = ImplementStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert isinstance(outcome, StageOutcome)
    assert outcome.status == StageStatus.COMPLETE
    assert outcome.stats is not None
    assert len(work.finalized_comments) == 1
    assert len(git.written_state) >= 1


@pytest.mark.asyncio
async def test_implement_stage_execute_failure_returns_blocked_outcome() -> None:
    ctx, work, *_ = _implement_ctx(
        runner_results=[RunResult(success=False, error="timeout")],
        project_root=Path("/tmp/test_implement_stage_fail"),
    )
    _populate_per_run_state(ctx)
    ctx.runner = FakeRunner([RunResult(success=False, error="timeout")])

    stage = ImplementStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status is None
    assert len(work.blocked) == 1


@pytest.mark.asyncio
async def test_implement_stage_happy_path_emits_effects_without_calling_adapters() -> (
    None
):
    """P3 step 5: execute() is adapter-pure; effects list carries the payload."""
    from a2sdlc.domain.effects import (
        CommentFinalize,
        CommitAndPush,
        LogMetric,
        SetCurrentStage,
        StateWrite,
    )

    ctx, work, git, _review, _runner = _implement_ctx(
        project_root=Path("/tmp/test_implement_stage_effects_happy")
    )
    _populate_per_run_state(ctx)

    stage = ImplementStage()
    outcome = await stage.execute(ctx)
    effects = stage.effects(ctx, outcome)

    assert work.finalized_comments == []
    assert git.written_state == []
    assert work.label_history == []
    assert work.blocked == []

    types_ = [type(e) for e in effects]
    assert CommentFinalize in types_
    assert StateWrite in types_
    assert CommitAndPush in types_
    assert SetCurrentStage in types_
    assert types_.count(LogMetric) == 5


@pytest.mark.asyncio
async def test_implement_stage_failure_emits_blocked_effects() -> None:
    """Failure → CommentFinalize + CommitAndPush + MarkBlocked, no StateWrite."""
    from a2sdlc.domain.effects import (
        CommentFinalize,
        CommitAndPush,
        MarkBlocked,
        StateWrite,
    )

    ctx, work, *_ = _implement_ctx(
        runner_results=[RunResult(success=False, error="timeout")],
        project_root=Path("/tmp/test_implement_stage_effects_fail"),
    )
    _populate_per_run_state(ctx)
    ctx.runner = FakeRunner([RunResult(success=False, error="timeout")])

    stage = ImplementStage()
    outcome = await stage.execute(ctx)
    effects = stage.effects(ctx, outcome)

    assert work.blocked == []
    types_ = [type(e) for e in effects]
    assert CommentFinalize in types_
    assert CommitAndPush in types_
    assert MarkBlocked in types_
    assert StateWrite not in types_


@pytest.mark.asyncio
async def test_implement_stage_execute_no_status_block_returns_blocked() -> None:
    """Runner returns success but no status block → blocked/no_status_block."""
    ctx, work, *_ = _implement_ctx(project_root=Path("/tmp/test_implement_stage_nsb"))
    _populate_per_run_state(ctx, "plain text, no fenced a2sdlc block")

    stage = ImplementStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status is None
    assert len(work.blocked) == 1


@pytest.mark.asyncio
async def test_implement_stage_execute_questions_marks_needs_input() -> None:
    """QUESTIONS status → next_stage returns None → mark_needs_input is called."""
    questions_output = '```a2sdlc\n{"status": "questions", "output": "Ambiguous"}\n```'
    ctx, work, *_ = _implement_ctx(project_root=Path("/tmp/test_implement_stage_q"))
    _populate_per_run_state(ctx, questions_output)

    stage = ImplementStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status == StageStatus.QUESTIONS
    assert len(work.needs_input) == 1


def test_implement_stage_preconditions_returns_none_in_p2() -> None:
    ctx, *_ = _implement_ctx(project_root=Path("/tmp/test_implement_stage_pre"))
    assert ImplementStage().preconditions(ctx) is None


def test_implement_stage_effects_is_empty_in_p2() -> None:
    ctx, *_ = _implement_ctx(project_root=Path("/tmp/test_implement_stage_eff"))
    outcome = StageOutcome(status=StageStatus.COMPLETE)
    assert ImplementStage().effects(ctx, outcome) == []


def test_implement_stage_name_and_valid_statuses() -> None:
    stage = ImplementStage()
    assert stage.name is StageName.IMPLEMENT
    assert stage.valid_statuses == frozenset(
        {StageStatus.COMPLETE, StageStatus.QUESTIONS}
    )
