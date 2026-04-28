"""Tests for ``_ensure_draft_pr`` — branch-match guard against state leakage."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.domain.models import GateConfig, GateMode, StageName, TicketState
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.pipeline.dispatch import _ensure_draft_pr


def _make_ctx() -> MagicMock:
    ctx = MagicMock(name="ctx")
    ctx.git = MagicMock(name="git")
    ctx.pr_lifecycle = MagicMock(name="pr_lifecycle")
    ctx.pr_lifecycle.create_draft.return_value = 99
    return ctx


def _make_intent(
    *,
    target_stage: StageName,
    branch: str,
    state: TicketState | None,
    event_pr_number: int | None = None,
) -> RunIntent:
    return RunIntent(
        event=PipelineEvent(
            key="42",
            trigger_stage=target_stage,
            pr_number=event_pr_number,
        ),
        target_stage=target_stage,
        clean_body="",
        user_prompt_override=None,
        gates=GateConfig(merge=GateMode.AUTO, spec=GateMode.AUTO),
        self_answer=False,
        state_mgr=None,
        state=state,
        branch=branch,
        base="main",
    )


def _state(branch: str, pr_number: int | None) -> TicketState:
    return TicketState(
        stage=StageName.SPEC,
        branch=branch,
        pr_number=pr_number,
        stage_run_id="test:run",
        last_updated="2026-04-28T00:00:00+00:00",
    )


@pytest.mark.unit
class TestEnsureDraftPr:
    def test_no_state_creates_draft_on_spec(self) -> None:
        ctx = _make_ctx()
        intent = _make_intent(
            target_stage=StageName.SPEC, branch="agent/42", state=None
        )

        pr_number = _ensure_draft_pr(ctx, intent)

        assert pr_number == 99
        ctx.git.commit_empty.assert_called_once()
        ctx.git.push.assert_called_once()
        ctx.pr_lifecycle.create_draft.assert_called_once()

    def test_state_owns_branch_with_pr_skips_creation(self) -> None:
        """Resume case — state belongs to this branch, trust the cached pr."""
        ctx = _make_ctx()
        intent = _make_intent(
            target_stage=StageName.SPEC,
            branch="agent/42",
            state=_state(branch="agent/42", pr_number=77),
        )

        pr_number = _ensure_draft_pr(ctx, intent)

        assert pr_number == 77
        ctx.git.commit_empty.assert_not_called()
        ctx.pr_lifecycle.create_draft.assert_not_called()

    def test_state_belongs_to_other_branch_creates_fresh(self) -> None:
        """Leaked-state case — state.branch != intent.branch.

        Reproduces smoke #46's failure mode: main carried a stale
        state.json from agent/44 (manual merge skipped strip_runtime_state).
        SPEC for agent/46 inherits the file but state.branch="agent/44"
        doesn't match → ignore the stale pr_number and open a new draft.
        """
        ctx = _make_ctx()
        intent = _make_intent(
            target_stage=StageName.SPEC,
            branch="agent/46",
            state=_state(branch="agent/44", pr_number=45),  # leaked
        )

        pr_number = _ensure_draft_pr(ctx, intent)

        assert pr_number == 99  # freshly created, ignored stale 45
        ctx.git.commit_empty.assert_called_once()
        ctx.pr_lifecycle.create_draft.assert_called_once()

    def test_non_spec_stage_does_not_create(self) -> None:
        ctx = _make_ctx()
        intent = _make_intent(
            target_stage=StageName.IMPLEMENT, branch="agent/42", state=None
        )

        pr_number = _ensure_draft_pr(ctx, intent)

        assert pr_number is None
        ctx.git.commit_empty.assert_not_called()

    def test_event_pr_number_overrides_state(self) -> None:
        """``intent.event.pr_number`` (e.g. PR-review event) wins."""
        ctx = _make_ctx()
        intent = _make_intent(
            target_stage=StageName.IMPLEMENT,
            branch="agent/42",
            state=_state(branch="agent/42", pr_number=10),
            event_pr_number=99,
        )

        pr_number = _ensure_draft_pr(ctx, intent)

        assert pr_number == 99
