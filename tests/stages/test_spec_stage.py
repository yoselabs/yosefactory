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
from a2sdlc.pipeline.preflight import PreflightOutcome, run_preflight
from a2sdlc.stages.spec import SpecStage
from tests.fakes import FakeRunner, default_run_result, make_dispatch_context


_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'


def _populate_per_run_state(
    ctx: Any, output: str = _COMPLETE_OUTPUT
) -> PreflightOutcome:
    """Mimic what dispatch() does before calling handler.execute.

    Runs preflight, builds pr_lifecycle + comment manager, loads stage
    config, and attaches a MagicMock RunHandle. Returns the pre for
    convenience.
    """
    pre = run_preflight(ctx)
    assert isinstance(pre, PreflightOutcome), f"preflight short-circuited: {pre!r}"
    ctx.pre = pre
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
    """N6: SpecStage().execute(ctx) completes with a StageOutcome, no dispatch needed."""
    ctx, work, git, _review, _runner = make_dispatch_context(
        project_root=Path("/tmp/test_spec_stage")
    )
    _populate_per_run_state(ctx)

    outcome = await SpecStage().execute(ctx)

    assert isinstance(outcome, StageOutcome)
    assert outcome.status == StageStatus.COMPLETE
    assert outcome.blocked is False
    assert outcome.error is None
    assert outcome.stats is not None
    # Happy path emits a state write + a stage comment finalized.
    assert len(work.finalized_comments) == 1
    assert len(git.written_state) >= 1


@pytest.mark.asyncio
async def test_spec_stage_execute_failure_returns_blocked_outcome() -> None:
    """Runner failure → StageOutcome(blocked=True, error=...) + ticket marked blocked."""
    ctx, work, *_ = make_dispatch_context(
        runner_results=[RunResult(success=False, error="timeout")],
        project_root=Path("/tmp/test_spec_stage_fail"),
    )
    _populate_per_run_state(ctx)
    # Override runner with the failure result (helper replaced it above).
    ctx.runner = FakeRunner([RunResult(success=False, error="timeout")])

    outcome = await SpecStage().execute(ctx)

    assert outcome.blocked is True
    assert outcome.error == "timeout"
    assert outcome.status is None
    assert len(work.blocked) == 1


def test_spec_stage_preconditions_returns_none_in_p2() -> None:
    """P2: preconditions is a no-op; preflight still owns gating."""
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_spec_stage_pre"))
    assert SpecStage().preconditions(ctx) is None


def test_spec_stage_effects_is_empty_in_p2() -> None:
    """P2: effects() returns [] — side effects still emitted inline in execute()."""
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_spec_stage_eff"))
    outcome = StageOutcome(status=StageStatus.COMPLETE)
    assert SpecStage().effects(ctx, outcome) == []


def test_spec_stage_name_and_valid_statuses() -> None:
    stage = SpecStage()
    assert stage.name is StageName.SPEC
    assert stage.valid_statuses == frozenset(
        {StageStatus.COMPLETE, StageStatus.QUESTIONS}
    )
