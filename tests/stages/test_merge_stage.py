"""N6 standalone-invocability + branch coverage for MergeStage.

MergeStage is deterministic (no AI). Tests cover:
- happy path: sync → strip → title → merge → mark_done, returns merged=True
- no-PR block path
- HUMAN gate without approval → blocked(waiting_for_approval)
- HUMAN gate with approval → merges
- strip_runtime_state exception is swallowed (warning logged, merge proceeds)
- preconditions/effects/name/valid_statuses
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.review import Approval
from a2sdlc.config import load_stage_config
from a2sdlc.domain.models import GateConfig, GateMode, StageName, StageStatus
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.pipeline.effects_apply import apply as apply_effects
from a2sdlc.pipeline.preflight import PreflightOutcome, run_preflight
from a2sdlc.stages.merge import MergeStage
from tests.fakes import make_dispatch_context


def _populate_per_run_state(ctx: Any, pr_number: int | None = 42) -> PreflightOutcome:
    pre = run_preflight(ctx)
    assert isinstance(pre, PreflightOutcome), f"preflight short-circuited: {pre!r}"
    ctx.pre = pre
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.comment = CommentManager(ctx.work, pre.event.key)
    ctx.comment.start(pre.target_stage.value)
    ctx.pr_number = pr_number
    ctx.stage_config = load_stage_config(pre.target_stage.value, ctx.config)
    ctx.run = MagicMock(name="RunHandle")
    return pre


def _merge_ctx(**kwargs: Any) -> Any:
    event = PipelineEvent(key="35", trigger_stage=StageName.MERGE)
    return make_dispatch_context(event=event, **kwargs)


@pytest.mark.asyncio
async def test_merge_stage_auto_gate_merges() -> None:
    """AUTO merge gate → no approval check, merges straight through."""
    ctx, work, git, review, _runner = _merge_ctx(
        project_root=Path("/tmp/test_merge_stage_auto"),
    )
    pre = _populate_per_run_state(ctx)
    pre.gates = GateConfig(merge=GateMode.AUTO)

    stage = MergeStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert isinstance(outcome, StageOutcome)
    assert outcome.merged is True
    assert outcome.blocked is False
    assert outcome.status is None
    # Merge lifecycle happened — applied via interpreter now.
    assert len(review.merged_prs) == 1
    assert review.merged_prs[0][0] == 42
    assert git.state_strips == 1
    assert ("35", "stage:done") in work.label_history


@pytest.mark.asyncio
async def test_merge_stage_happy_path_emits_effects_without_calling_adapters() -> None:
    """P3 step 7: execute() is adapter-pure; effects drive the merge sequence."""
    from a2sdlc.domain.effects import (
        CommentFinalize,
        MarkDone,
        MergePR,
        StripRuntimeState,
        SyncBase,
        UpdatePRTitle,
    )

    ctx, work, git, review, _runner = _merge_ctx(
        project_root=Path("/tmp/test_merge_stage_effects_happy"),
    )
    pre = _populate_per_run_state(ctx)
    pre.gates = GateConfig(merge=GateMode.AUTO)

    stage = MergeStage()
    outcome = await stage.execute(ctx)
    effects = stage.effects(ctx, outcome)

    # execute() did not touch adapters.
    assert review.merged_prs == []
    assert git.state_strips == 0
    assert work.label_history == []
    assert work.finalized_comments == []

    types_ = [type(e) for e in effects]
    assert SyncBase in types_
    assert StripRuntimeState in types_
    assert UpdatePRTitle in types_
    assert MergePR in types_
    assert CommentFinalize in types_
    assert MarkDone in types_


@pytest.mark.asyncio
async def test_merge_stage_no_pr_blocks() -> None:
    ctx, work, _git, _review, _runner = _merge_ctx(
        project_root=Path("/tmp/test_merge_stage_nopr"),
    )
    _populate_per_run_state(ctx, pr_number=None)

    stage = MergeStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.blocked is True
    assert outcome.merged is False
    assert outcome.error is not None
    assert "No PR found" in outcome.error
    assert len(work.blocked) == 1


@pytest.mark.asyncio
async def test_merge_stage_human_gate_without_approval_blocks() -> None:
    ctx, _work, _git, review, _runner = _merge_ctx(
        project_root=Path("/tmp/test_merge_stage_human_no_approval"),
    )
    pre = _populate_per_run_state(ctx)
    pre.gates = GateConfig(merge=GateMode.HUMAN)

    stage = MergeStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.blocked is True
    assert outcome.error == "waiting_for_approval"
    assert review.merged_prs == []


@pytest.mark.asyncio
async def test_merge_stage_human_gate_with_approval_merges() -> None:
    ctx, _work, _git, review, _runner = _merge_ctx(
        project_root=Path("/tmp/test_merge_stage_human_approved"),
    )
    # Seed a non-bot approval into the fake review adapter.
    review._approvals.append(Approval(user="denis", is_bot=False))  # type: ignore[attr-defined]
    pre = _populate_per_run_state(ctx)
    pre.gates = GateConfig(merge=GateMode.HUMAN)

    stage = MergeStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.merged is True
    assert len(review.merged_prs) == 1


@pytest.mark.asyncio
async def test_merge_stage_strip_runtime_state_failure_is_swallowed() -> None:
    """If strip_runtime_state raises, merge still proceeds (logged as warning)."""
    ctx, _work, git, review, _runner = _merge_ctx(
        project_root=Path("/tmp/test_merge_stage_strip_fail"),
    )
    pre = _populate_per_run_state(ctx)
    pre.gates = GateConfig(merge=GateMode.AUTO)

    def _boom() -> None:
        raise RuntimeError("strip failed")

    git.strip_runtime_state = _boom  # type: ignore[method-assign]

    stage = MergeStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.merged is True
    assert len(review.merged_prs) == 1


def test_merge_stage_preconditions_returns_none_in_p2() -> None:
    ctx, *_ = _merge_ctx(project_root=Path("/tmp/test_merge_stage_pre"))
    assert MergeStage().preconditions(ctx) is None


def test_merge_stage_effects_is_empty_in_p2() -> None:
    ctx, *_ = _merge_ctx(project_root=Path("/tmp/test_merge_stage_eff"))
    outcome = StageOutcome(merged=True)
    assert MergeStage().effects(ctx, outcome) == []


def test_merge_stage_name_and_valid_statuses() -> None:
    stage = MergeStage()
    assert stage.name is StageName.MERGE
    assert stage.valid_statuses == frozenset[StageStatus]()
