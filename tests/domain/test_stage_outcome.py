"""Tests for StageOutcome + InlineComment — structured stage result."""

from __future__ import annotations

import pytest

from a2sdlc.domain.models import StageName, StageStatus
from a2sdlc.domain.stage_outcome import InlineComment, StageOutcome
from a2sdlc.domain.stats import StageRunStats


@pytest.mark.unit
class TestInlineComment:
    def test_single_line(self) -> None:
        ic = InlineComment(
            file="src/auth.py",
            line_start=42,
            line_end=42,
            body="Missing input validation.",
        )
        assert ic.side == "RIGHT"

    def test_multi_line_range(self) -> None:
        ic = InlineComment(
            file="src/db.py",
            line_start=10,
            line_end=18,
            body="N+1 query pattern.",
            side="RIGHT",
        )
        assert ic.line_end - ic.line_start == 8

    def test_frozen(self) -> None:
        ic = InlineComment(
            file="src/a.py",
            line_start=1,
            line_end=1,
            body="x",
        )
        with pytest.raises(Exception):
            ic.body = "y"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(Exception):
            InlineComment(
                file="src/a.py",
                line_start=1,
                line_end=1,
                body="x",
                unexpected="oops",  # ty: ignore[unknown-argument]
            )

    def test_side_validation(self) -> None:
        with pytest.raises(Exception):
            InlineComment(
                file="src/a.py",
                line_start=1,
                line_end=1,
                body="x",
                side="INVALID",  # ty: ignore[invalid-argument-type]
            )

    def test_round_trip(self) -> None:
        ic = InlineComment(
            file="src/auth.py",
            line_start=40,
            line_end=45,
            body="Input not validated. Use `validate()`.",
            side="RIGHT",
        )
        restored = InlineComment.model_validate_json(ic.model_dump_json())
        assert restored == ic


@pytest.mark.unit
class TestStageOutcome:
    def test_defaults(self) -> None:
        outcome = StageOutcome()
        assert outcome.status is None
        assert outcome.output_text == ""
        assert outcome.inline_comments == []
        assert outcome.stats is None
        assert outcome.merged is None
        assert outcome.next_stage_hint is None

    def test_ai_stage_outcome(self) -> None:
        stats = StageRunStats(cost_usd=0.42, tokens_in=1000, tokens_out=500)
        outcome = StageOutcome(
            status=StageStatus.COMPLETE,
            output_text="Spec produced.",
            stats=stats,
        )
        assert outcome.status is StageStatus.COMPLETE
        assert outcome.stats is stats  # identity preserved (arbitrary_types)

    def test_review_outcome_with_inline_comments(self) -> None:
        comments = [
            InlineComment(
                file="src/auth.py",
                line_start=42,
                line_end=42,
                body="bad",
            ),
            InlineComment(
                file="src/db.py",
                line_start=10,
                line_end=18,
                body="N+1",
            ),
        ]
        outcome = StageOutcome(
            status=StageStatus.CHANGES_REQUESTED,
            output_text="See inline comments.",
            inline_comments=comments,
        )
        assert len(outcome.inline_comments) == 2
        assert outcome.inline_comments[0].file == "src/auth.py"

    def test_merge_outcome(self) -> None:
        outcome = StageOutcome(merged=True)
        assert outcome.merged is True
        assert outcome.status is None  # MERGE has no StageStatus

    def test_next_stage_hint(self) -> None:
        outcome = StageOutcome(next_stage_hint=StageName.MERGE)
        assert outcome.next_stage_hint is StageName.MERGE

    def test_extra_forbid(self) -> None:
        with pytest.raises(Exception):
            StageOutcome(
                output_text="x",
                unexpected="oops",  # ty: ignore[unknown-argument]
            )
