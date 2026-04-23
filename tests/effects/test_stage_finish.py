"""L1 tests for ``pipeline.stage_finish``.

Pure-function translator lifted out of dispatch in P4 step 8. Three
arms matter: pause (MarkBlocked / AwaitHumanDecision), merged happy
path (MERGE, no status), and AI-stage happy path (status + stats).
"""

from __future__ import annotations

import pytest

from a2sdlc.domain.effects import AwaitHumanDecision, CommentFinalize, MarkBlocked
from a2sdlc.domain.models import GateConfig, StageName, StageStatus
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.effects.stage_finish import (
    outcome_to_dispatch_result,
    pipeline_pause_reason,
)


def _intent(stage: StageName = StageName.SPEC) -> RunIntent:
    return RunIntent(
        event=PipelineEvent(key="ABC-1", trigger_stage=stage),
        target_stage=stage,
        clean_body="body",
        user_prompt_override=None,
        gates=GateConfig(),
        self_answer=False,
        state_mgr=None,
        state=None,
        base="main",
        branch="feat/ABC-1",
    )


@pytest.mark.unit
class TestPipelinePauseReason:
    def test_mark_blocked_wins(self) -> None:
        assert pipeline_pause_reason([MarkBlocked(reason="boom")]) == "boom"

    def test_await_human_decision_wins(self) -> None:
        eff = AwaitHumanDecision(kind="approval", reason="needs_review")
        assert pipeline_pause_reason([eff]) == "needs_review"

    def test_none_when_no_pause_arm(self) -> None:
        assert pipeline_pause_reason([]) is None
        assert pipeline_pause_reason([CommentFinalize(body="x")]) is None

    def test_first_pause_arm_wins(self) -> None:
        effects = [CommentFinalize(body="x"), MarkBlocked(reason="first")]
        assert pipeline_pause_reason(effects) == "first"


@pytest.mark.unit
class TestOutcomeToDispatchResult:
    def test_pause_branch_blocked_with_reason(self) -> None:
        intent = _intent()
        outcome = StageOutcome(
            output_text="partial",
            prepared_effects=[MarkBlocked(reason="git_blocked")],
        )
        result = outcome_to_dispatch_result(intent, outcome)
        assert result.stage is StageName.SPEC
        assert result.blocked is True
        assert result.error == "git_blocked"
        assert result.output == "partial"

    def test_merged_happy_path(self) -> None:
        intent = _intent(StageName.MERGE)
        outcome = StageOutcome(merged=True)
        result = outcome_to_dispatch_result(intent, outcome)
        assert result.stage is StageName.MERGE
        assert result.blocked is False
        assert result.status is None
        assert result.error is None

    def test_ai_stage_happy_path_carries_status(self) -> None:
        intent = _intent(StageName.IMPLEMENT)
        outcome = StageOutcome(
            status=StageStatus.COMPLETE,
            output_text="spec body",
            next_stage_hint=StageName.REVIEW,
        )
        result = outcome_to_dispatch_result(intent, outcome)
        assert result.stage is StageName.IMPLEMENT
        assert result.status is StageStatus.COMPLETE
        assert result.next_stage is StageName.REVIEW
        assert result.blocked is False
        assert result.output == "spec body"
        assert result.error is None

    def test_non_paused_without_status_or_merged_asserts(self) -> None:
        intent = _intent()
        outcome = StageOutcome()
        with pytest.raises(AssertionError):
            outcome_to_dispatch_result(intent, outcome)
