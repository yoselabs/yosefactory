"""Dispatch integration tests — fake adapters, real dispatch logic."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from a2sdlc.adapters.protocols import DispatchInput
from a2sdlc.config import ProjectConfig
from a2sdlc.dispatch import DispatchContext, dispatch
from a2sdlc.models import BranchState, StageName, StageStatus
from a2sdlc.runner import RunResult
from tests.fakes import FakeGitAdapter, FakeRunner, FakeTicketAdapter


# ── Helpers ──��──────────────────────────────────────────────────────


def _success_output(status: str = "complete") -> str:
    return f'Done.\n\n```a2sdlc\n{{"status": "{status}"}}\n```'


def _success_result(status: str = "complete") -> RunResult:
    return RunResult(
        success=True,
        output=_success_output(status),
        input_tokens=1000,
        output_tokens=500,
        total_cost_usd=0.05,
        duration_ms=30000,
    )


def _failure_result(error: str = "sdk_error") -> RunResult:
    return RunResult(
        success=False,
        output="",
        error=error,
        input_tokens=100,
        output_tokens=0,
        total_cost_usd=0.01,
        duration_ms=5000,
    )


def _no_status_result() -> RunResult:
    return RunResult(
        success=True,
        output="Some output without a status block.",
        input_tokens=500,
        output_tokens=200,
        total_cost_usd=0.03,
        duration_ms=15000,
    )


def _state_json(
    stage: str = "spec",
    status: str = "complete",
    review_cycles: int = 0,
    base_branch: str = "main",
) -> str:
    return BranchState(
        stage=StageName(stage),
        status=StageStatus(status),
        base_branch=base_branch,
        review_cycles=review_cycles,
        last_updated="2026-01-01T00:00:00+00:00",
    ).model_dump_json(indent=2)


@dataclass
class _Harness:
    """Holds both the dispatch context and typed references to fakes."""

    ctx: DispatchContext
    tickets: FakeTicketAdapter
    git: FakeGitAdapter
    runner: FakeRunner


def _make(
    event: DispatchInput | None = None,
    result: RunResult | list[RunResult] | None = None,
    labels: list[str] | None = None,
    conflict: bool = False,
    state_json: str | None = None,
    auto_proceed: bool = True,
    auto_merge: bool = False,
    auto_spec: bool = False,
    pr_for_branch: int | None = None,
    skip: bool = False,
) -> _Harness:
    ev = None if skip else (event or DispatchInput(key="TEST-1", stage=StageName.SPEC))
    tickets = FakeTicketAdapter(
        event=ev,
        labels=labels or [],
        pr_for_branch=pr_for_branch,
    )
    git = FakeGitAdapter(state_json=state_json, conflict_on_setup=conflict)
    runner = FakeRunner(result=result or _success_result())
    ctx = DispatchContext(
        tickets=tickets,
        git=git,
        runner=runner,
        config=ProjectConfig(
            auto_spec=auto_spec,
            auto_proceed=auto_proceed,
            auto_merge=auto_merge,
        ),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test.dispatch"),
    )
    return _Harness(ctx=ctx, tickets=tickets, git=git, runner=runner)


# ── Spec stage ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestDispatchSpecComplete:
    @pytest.mark.asyncio
    async def test_spec_complete_auto_proceed(self) -> None:
        """Spec complete + auto_proceed → sets stage:implement label."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
            auto_proceed=True,
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.SPEC
        assert r.status == StageStatus.COMPLETE
        assert r.next_stage == StageName.IMPLEMENT
        assert r.blocked is False

        # Should have set stage:implement (transition), NOT re-set stage:spec
        assert ("T-1", "stage:implement") in h.tickets.label_history

    @pytest.mark.asyncio
    async def test_spec_complete_gate_closed(self) -> None:
        """Spec complete + auto_proceed=False → does NOT set next label."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
            auto_proceed=False,
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.SPEC
        assert r.status == StageStatus.COMPLETE
        assert r.next_stage is None
        assert r.blocked is False

        # Gate closed — no transition label set at all
        assert ("T-1", "stage:implement") not in h.tickets.label_history


@pytest.mark.unit
class TestDispatchSpecQuestions:
    @pytest.mark.asyncio
    async def test_questions_waits(self) -> None:
        """Spec questions → next=None, waits for human."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("questions"),
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.SPEC
        assert r.status == StageStatus.QUESTIONS
        assert r.next_stage is None
        assert r.blocked is False


# ── Implement stage ─────────────────────────────────────────────────


@pytest.mark.unit
class TestDispatchImplementComplete:
    @pytest.mark.asyncio
    async def test_implement_complete_triggers_review(self) -> None:
        """Implement complete → sets stage:review label (no gate)."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.IMPLEMENT),
            result=_success_result("complete"),
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.IMPLEMENT
        assert r.status == StageStatus.COMPLETE
        assert r.next_stage == StageName.REVIEW
        assert ("T-1", "stage:review") in h.tickets.label_history


# ── Review stage ────────────────────────────────────────────────────


@pytest.mark.unit
class TestDispatchReview:
    @pytest.mark.asyncio
    async def test_review_approved_auto_merge(self) -> None:
        """Review approved + auto_merge → sets stage:merge, posts APPROVE review."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.REVIEW, pr_number=42),
            result=_success_result("approved"),
            auto_merge=True,
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.REVIEW
        assert r.status == StageStatus.APPROVED
        assert r.next_stage == StageName.MERGE

        assert ("T-1", "stage:merge") in h.tickets.label_history
        # Should post an APPROVE review
        assert len(h.tickets.reviews) == 1
        assert h.tickets.reviews[0][0] == 42
        assert h.tickets.reviews[0][2] == "APPROVE"

    @pytest.mark.asyncio
    async def test_review_approved_no_auto_merge(self) -> None:
        """Review approved + auto_merge=False → does NOT set next label."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.REVIEW, pr_number=42),
            result=_success_result("approved"),
            auto_merge=False,
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.REVIEW
        assert r.status == StageStatus.APPROVED
        assert r.next_stage is None

        assert ("T-1", "stage:merge") not in h.tickets.label_history
        # Still posts the APPROVE review
        assert len(h.tickets.reviews) == 1
        assert h.tickets.reviews[0][2] == "APPROVE"

    @pytest.mark.asyncio
    async def test_review_changes_requested_loops(self) -> None:
        """Review changes_requested → sets stage:implement, increments review_cycles."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.REVIEW, pr_number=42),
            result=_success_result("changes_requested"),
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.REVIEW
        assert r.status == StageStatus.CHANGES_REQUESTED
        assert r.next_stage == StageName.IMPLEMENT

        assert ("T-1", "stage:implement") in h.tickets.label_history
        # Should post a REQUEST_CHANGES review
        assert len(h.tickets.reviews) == 1
        assert h.tickets.reviews[0][2] == "REQUEST_CHANGES"

        # Check state was written with incremented review_cycles
        assert len(h.git.written_state) == 1
        written = json.loads(h.git.written_state[0])
        assert written["review_cycles"] == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks(self) -> None:
        """Review with review_cycles >= max → blocked without running AI."""
        state = _state_json(stage="review", status="changes_requested", review_cycles=3)
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.REVIEW),
            state_json=state,
        )
        r = await dispatch(h.ctx)

        assert r.blocked is True
        assert "Circuit breaker" in (r.error or "")

        # Runner should NOT have been called
        assert len(h.runner.calls) == 0

        # Should be marked as blocked
        assert len(h.tickets.blocked) == 1


# ── Merge stage ─────────────���───────────────────────────────────────


@pytest.mark.unit
class TestDispatchMerge:
    @pytest.mark.asyncio
    async def test_merge_squashes_and_sets_done(self) -> None:
        """Merge with PR → merges and sets stage:done."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.MERGE, pr_number=99),
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.MERGE
        assert r.blocked is False

        assert len(h.tickets.merged_prs) == 1
        assert h.tickets.merged_prs[0][0] == 99
        assert ("T-1", "stage:done") in h.tickets.label_history

    @pytest.mark.asyncio
    async def test_merge_finds_pr_from_branch(self) -> None:
        """Merge without pr_number → looks up PR from branch."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.MERGE),
            pr_for_branch=77,
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.MERGE
        assert r.blocked is False

        assert len(h.tickets.merged_prs) == 1
        assert h.tickets.merged_prs[0][0] == 77

    @pytest.mark.asyncio
    async def test_merge_no_pr_blocks(self) -> None:
        """Merge with no PR found → blocked."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.MERGE),
            pr_for_branch=None,
        )
        r = await dispatch(h.ctx)

        assert r.stage == StageName.MERGE
        assert r.blocked is True
        assert "No PR found" in (r.error or "")


# ── Error handling ──────���────────────────────────��──────────────────


@pytest.mark.unit
class TestDispatchErrors:
    @pytest.mark.asyncio
    async def test_skip_event(self) -> None:
        """No event → SkipEvent → error in result."""
        h = _make(skip=True)
        r = await dispatch(h.ctx)

        assert r.error is not None
        assert "no event" in r.error

    @pytest.mark.asyncio
    async def test_git_conflict_blocks(self) -> None:
        """Git conflict on setup → blocked."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            conflict=True,
        )
        r = await dispatch(h.ctx)

        assert r.blocked is True
        assert "conflict" in (r.error or "").lower()
        assert len(h.tickets.blocked) == 1

    @pytest.mark.asyncio
    async def test_stage_failure_blocks(self) -> None:
        """Runner failure → blocked."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_failure_result("timeout (60min)"),
        )
        r = await dispatch(h.ctx)

        assert r.blocked is True
        assert r.error == "timeout (60min)"
        assert len(h.tickets.blocked) == 1

    @pytest.mark.asyncio
    async def test_no_status_block_blocks(self) -> None:
        """Output without a2sdlc block → blocked."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_no_status_result(),
        )
        r = await dispatch(h.ctx)

        assert r.blocked is True
        assert r.error == "no_status_block"


# ── Auto-spec ───────────────���───────────────────────────��───────────


@pytest.mark.unit
class TestDispatchAutoSpec:
    @pytest.mark.asyncio
    async def test_auto_spec_injects_prompt(self) -> None:
        """auto_spec=True on spec stage → system_prompt has prefix."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
            auto_spec=True,
        )
        await dispatch(h.ctx)

        assert len(h.runner.calls) == 1
        system_prompt = h.runner.calls[0].system_prompt
        assert system_prompt.startswith("IMPORTANT: Make your best judgment")

    @pytest.mark.asyncio
    async def test_auto_spec_not_on_implement(self) -> None:
        """auto_spec=True on implement stage → system_prompt has NO prefix."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.IMPLEMENT),
            result=_success_result("complete"),
            auto_spec=True,
        )
        await dispatch(h.ctx)

        assert len(h.runner.calls) == 1
        system_prompt = h.runner.calls[0].system_prompt
        assert not system_prompt.startswith("IMPORTANT:")


# ── State persistence ─────────────────────────────────────────────


@pytest.mark.unit
class TestDispatchState:
    @pytest.mark.asyncio
    async def test_writes_state_and_pushes(self) -> None:
        """Successful stage → writes state, commits, pushes."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
        )
        await dispatch(h.ctx)

        assert len(h.git.written_state) == 1
        assert len(h.git.commits) == 1
        assert len(h.git.pushes) == 1

        state = json.loads(h.git.written_state[0])
        assert state["stage"] == "spec"
        assert state["status"] == "complete"

    @pytest.mark.asyncio
    async def test_preserves_base_branch_from_state(self) -> None:
        """Existing state with custom base → preserved in new state."""
        existing = _state_json(stage="spec", status="complete", base_branch="develop")
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.IMPLEMENT),
            result=_success_result("complete"),
            state_json=existing,
        )
        await dispatch(h.ctx)

        state = json.loads(h.git.written_state[0])
        assert state["base_branch"] == "develop"


@pytest.mark.unit
class TestDispatchBranchPassing:
    @pytest.mark.asyncio
    async def test_passes_branch_to_runner(self) -> None:
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
        )
        await dispatch(h.ctx)

        assert len(h.runner.calls) == 1
        assert h.runner.calls[0].branch == "a2sdlc/T-1"


@pytest.mark.unit
class TestDispatchStatusBar:
    @pytest.mark.asyncio
    async def test_final_comment_has_status_bar(self) -> None:
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
        )
        await dispatch(h.ctx)

        final_body = h.tickets.updated_comments[-1][2]
        assert "| Model |" in final_body
        assert "claude-sonnet-4-6" in final_body

    @pytest.mark.asyncio
    async def test_error_comment_has_status_bar(self) -> None:
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_failure_result("timeout (60min)"),
        )
        await dispatch(h.ctx)

        final_body = h.tickets.updated_comments[-1][2]
        assert "🚨" in final_body
        assert "| Model |" in final_body
