"""L1 tests for the Effect ADT — construction, equality, match exhaustiveness."""

from __future__ import annotations

import pytest

from a2sdlc.domain.effects import (
    CleanupBase,
    CommentFinalize,
    CommentStart,
    CommitAndPush,
    CreateDraftPR,
    Effect,
    LogArtifact,
    LogMetric,
    MarkBlocked,
    MarkDone,
    MarkNeedsInput,
    MergePR,
    PostInlineReview,
    PostReview,
    RunQualityGate,
    RunSecretsScan,
    SetCurrentStage,
    StateWrite,
    Transition,
    UpdatePR,
)
from a2sdlc.domain.models import StageName, TicketState
from a2sdlc.domain.stage_outcome import InlineComment


@pytest.mark.unit
class TestEffectArms:
    """Each arm constructs + is frozen + hashable."""

    def test_mark_blocked_construct(self) -> None:
        e = MarkBlocked(reason="timeout")
        assert e.reason == "timeout"

    def test_mark_done_no_args(self) -> None:
        assert MarkDone() == MarkDone()

    def test_mark_needs_input_no_args(self) -> None:
        assert MarkNeedsInput() == MarkNeedsInput()

    def test_set_current_stage(self) -> None:
        e = SetCurrentStage(stage=StageName.IMPLEMENT)
        assert e.stage is StageName.IMPLEMENT

    def test_comment_finalize(self) -> None:
        assert CommentFinalize(body="done").body == "done"

    def test_comment_start(self) -> None:
        assert CommentStart(stage=StageName.SPEC).stage is StageName.SPEC

    def test_create_draft_pr(self) -> None:
        e = CreateDraftPR(branch="agent/35", base="main", ticket_key="35")
        assert e.branch == "agent/35"

    def test_update_pr(self) -> None:
        e = UpdatePR(pr_number=1, title="t", body="b", ticket_key="35")
        assert e.pr_number == 1

    def test_merge_pr_default_method(self) -> None:
        assert MergePR(pr_number=7).method == "squash"

    def test_merge_pr_explicit_method(self) -> None:
        assert MergePR(pr_number=7, method="rebase").method == "rebase"

    def test_post_review(self) -> None:
        e = PostReview(pr_number=1, verdict="APPROVE", body="LGTM")
        assert e.verdict == "APPROVE"

    def test_post_inline_review(self) -> None:
        ic = InlineComment(file="a.py", line_start=1, line_end=1, body="fix")
        e = PostInlineReview(pr_number=1, comments=[ic])
        assert len(e.comments) == 1
        assert e.comments[0].file == "a.py"

    def test_post_inline_review_empty_allowed(self) -> None:
        assert PostInlineReview(pr_number=1, comments=[]).comments == []

    def test_commit_and_push(self) -> None:
        e = CommitAndPush(message="chore", paths=(".a2sdlc/state.json",))
        assert e.paths == (".a2sdlc/state.json",)

    def test_cleanup_base(self) -> None:
        assert CleanupBase(base="main").base == "main"

    def test_transition_to_next(self) -> None:
        assert Transition(next=StageName.MERGE).next is StageName.MERGE

    def test_transition_to_none_waits_for_human(self) -> None:
        assert Transition(next=None).next is None

    def test_log_metric(self) -> None:
        e = LogMetric(key="tokens_in", value=1234.0)
        assert e.value == 1234.0

    def test_log_artifact(self) -> None:
        assert LogArtifact(path="/tmp/a").path == "/tmp/a"

    def test_run_quality_gate(self) -> None:
        assert RunQualityGate(command="pytest").command == "pytest"

    def test_run_secrets_scan(self) -> None:
        assert RunSecretsScan(paths=("src/",)).paths == ("src/",)

    def test_state_write(self) -> None:
        ts = TicketState(
            stage=StageName.SPEC,
            branch="agent/1",
            stage_run_id="r",
            last_updated="2026-04-25T00:00:00Z",
        )
        assert StateWrite(state=ts).state.stage is StageName.SPEC


@pytest.mark.unit
class TestEffectImmutability:
    def test_frozen(self) -> None:
        e = MarkBlocked(reason="x")
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            e.reason = "y"  # ty: ignore[invalid-assignment]

    def test_equality_by_value(self) -> None:
        assert MarkBlocked(reason="x") == MarkBlocked(reason="x")
        assert MarkBlocked(reason="x") != MarkBlocked(reason="y")


@pytest.mark.unit
class TestEffectMatch:
    """Verify the union is exhaustively matchable. Serves as a compile-time
    guard for interpreter coverage — each arm must be handled somewhere."""

    def _label(self, eff: Effect) -> str:
        match eff:
            case StateWrite():
                return "state_write"
            case CommentStart():
                return "comment_start"
            case CommentFinalize():
                return "comment_finalize"
            case CreateDraftPR():
                return "create_draft_pr"
            case UpdatePR():
                return "update_pr"
            case MergePR():
                return "merge_pr"
            case PostReview():
                return "post_review"
            case PostInlineReview():
                return "post_inline_review"
            case SetCurrentStage():
                return "set_current_stage"
            case MarkBlocked():
                return "mark_blocked"
            case MarkDone():
                return "mark_done"
            case MarkNeedsInput():
                return "mark_needs_input"
            case CommitAndPush():
                return "commit_and_push"
            case CleanupBase():
                return "cleanup_base"
            case Transition():
                return "transition"
            case LogMetric():
                return "log_metric"
            case LogArtifact():
                return "log_artifact"
            case RunQualityGate():
                return "run_quality_gate"
            case RunSecretsScan():
                return "run_secrets_scan"

    def test_match_covers_every_arm(self) -> None:
        ic = InlineComment(file="a.py", line_start=1, line_end=1, body="b")
        ts = TicketState(
            stage=StageName.SPEC,
            branch="b",
            stage_run_id="r",
            last_updated="2026-04-25T00:00:00Z",
        )
        arms: list[Effect] = [
            StateWrite(state=ts),
            CommentStart(stage=StageName.SPEC),
            CommentFinalize(body="b"),
            CreateDraftPR(branch="b", base="main", ticket_key="k"),
            UpdatePR(pr_number=1, title="t", body="b", ticket_key="k"),
            MergePR(pr_number=1),
            PostReview(pr_number=1, verdict="APPROVE", body="b"),
            PostInlineReview(pr_number=1, comments=[ic]),
            SetCurrentStage(stage=StageName.IMPLEMENT),
            MarkBlocked(reason="r"),
            MarkDone(),
            MarkNeedsInput(),
            CommitAndPush(message="m", paths=("p",)),
            CleanupBase(base="main"),
            Transition(next=None),
            LogMetric(key="k", value=1.0),
            LogArtifact(path="/p"),
            RunQualityGate(command="c"),
            RunSecretsScan(paths=("src/",)),
        ]
        labels = [self._label(a) for a in arms]
        # All 19 arms matched (no None returned).
        assert all(lbl for lbl in labels)
        assert len(set(labels)) == 19
