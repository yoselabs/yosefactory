"""Tests for a2sdlc.models — Pydantic models and structured output parsing."""

from __future__ import annotations

from typing import Any

import pytest

from a2sdlc.models import (
    BranchState,
    GateConfig,
    GateMode,
    StageName,
    StageResult,
    StageStatus,
    TicketState,
    extract_result,
    strip_status_block,
)


@pytest.mark.unit
class TestStageStatus:
    def test_values(self) -> None:
        assert StageStatus.COMPLETE == "complete"
        assert StageStatus.QUESTIONS == "questions"
        assert StageStatus.APPROVED == "approved"
        assert StageStatus.CHANGES_REQUESTED == "changes_requested"

    def test_from_string(self) -> None:
        assert StageStatus("complete") is StageStatus.COMPLETE
        assert StageStatus("approved") is StageStatus.APPROVED


@pytest.mark.unit
class TestStageResult:
    def test_parse_complete(self) -> None:
        r = StageResult.model_validate_json('{"status": "complete"}')
        assert r.status is StageStatus.COMPLETE

    def test_parse_questions(self) -> None:
        r = StageResult.model_validate_json('{"status": "questions"}')
        assert r.status is StageStatus.QUESTIONS

    def test_parse_approved(self) -> None:
        r = StageResult.model_validate_json('{"status": "approved"}')
        assert r.status is StageStatus.APPROVED

    def test_parse_changes_requested(self) -> None:
        r = StageResult.model_validate_json('{"status": "changes_requested"}')
        assert r.status is StageStatus.CHANGES_REQUESTED

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(Exception):
            StageResult.model_validate_json('{"status": "invalid"}')


@pytest.mark.unit
class TestBranchState:
    def test_roundtrip(self) -> None:
        state = BranchState(
            stage=StageName.SPEC,
            status=StageStatus.COMPLETE,
            last_updated="2026-04-05T12:00:00Z",
        )
        dumped = state.model_dump_json()
        restored = BranchState.model_validate_json(dumped)
        assert restored.stage == StageName.SPEC
        assert restored.status == StageStatus.COMPLETE


@pytest.mark.unit
class TestExtractResult:
    def test_valid_block(self) -> None:
        output = 'Some text\n\n```a2sdlc\n{"status": "complete"}\n```\n'
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.COMPLETE

    def test_questions_block(self) -> None:
        output = 'Questions:\n1. Foo?\n\n```a2sdlc\n{"status": "questions"}\n```'
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.QUESTIONS

    def test_no_block(self) -> None:
        output = "Just some text without any status block."
        assert extract_result(output) is None

    def test_malformed_json(self) -> None:
        output = "```a2sdlc\n{broken json\n```"
        assert extract_result(output) is None

    def test_missing_closing_fence(self) -> None:
        output = '```a2sdlc\n{"status": "complete"}\n'
        assert extract_result(output) is None

    def test_last_block_wins(self) -> None:
        output = (
            '```a2sdlc\n{"status": "questions"}\n```\n'
            "More work...\n"
            '```a2sdlc\n{"status": "complete"}\n```\n'
        )
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.COMPLETE

    def test_block_with_surrounding_text(self) -> None:
        output = (
            "I've completed the spec.\n\n"
            "Spec: docs/superpowers/specs/2026-04-05-ISSUE-11.md\n\n"
            '```a2sdlc\n{"status": "complete"}\n```\n\n'
            "Some trailing text"
        )
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.COMPLETE


@pytest.mark.unit
class TestStripStatusBlock:
    def test_strip_block(self) -> None:
        output = 'Summary text\n\n```a2sdlc\n{"status": "complete"}\n```\n\nTrailing'
        stripped = strip_status_block(output)
        assert "a2sdlc" not in stripped
        assert "Summary text" in stripped
        assert "Trailing" in stripped

    def test_no_block_returns_original(self) -> None:
        output = "Just text, no block"
        assert strip_status_block(output) == output

    def test_block_at_end(self) -> None:
        output = 'Summary\n\n```a2sdlc\n{"status": "complete"}\n```'
        stripped = strip_status_block(output)
        assert stripped == "Summary"


@pytest.mark.unit
class TestGateMode:
    def test_values(self) -> None:
        assert GateMode.AUTO == "auto"
        assert GateMode.HUMAN == "human"

    def test_from_string(self) -> None:
        assert GateMode("auto") is GateMode.AUTO
        assert GateMode("human") is GateMode.HUMAN

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            GateMode("invalid")


@pytest.mark.unit
class TestGateConfig:
    def test_defaults(self) -> None:
        cfg = GateConfig()
        assert cfg.merge is GateMode.HUMAN
        assert cfg.review is GateMode.AUTO

    def test_override_merge(self) -> None:
        cfg = GateConfig(merge=GateMode.AUTO)
        assert cfg.merge is GateMode.AUTO
        assert cfg.review is GateMode.AUTO

    def test_override_review(self) -> None:
        cfg = GateConfig(review=GateMode.HUMAN)
        assert cfg.review is GateMode.HUMAN
        assert cfg.merge is GateMode.HUMAN

    def test_roundtrip(self) -> None:
        cfg = GateConfig(merge=GateMode.AUTO, review=GateMode.HUMAN)
        restored = GateConfig.model_validate_json(cfg.model_dump_json())
        assert restored.merge is GateMode.AUTO
        assert restored.review is GateMode.HUMAN


@pytest.mark.unit
class TestTicketState:
    def _make(self, **kwargs: Any) -> TicketState:
        defaults: dict[str, Any] = {
            "stage": StageName.SPEC,
            "branch": "feature/TEST-1",
            "stage_run_id": "run-abc123",
            "last_updated": "2026-04-11T10:00:00Z",
        }
        defaults.update(kwargs)
        return TicketState(**defaults)

    def test_required_fields(self) -> None:
        ts = self._make()
        assert ts.stage is StageName.SPEC
        assert ts.branch == "feature/TEST-1"
        assert ts.stage_run_id == "run-abc123"
        assert ts.last_updated == "2026-04-11T10:00:00Z"

    def test_defaults(self) -> None:
        ts = self._make()
        assert ts.status is None
        assert ts.base_branch == "main"
        assert ts.pr_number is None
        assert ts.comment_id is None
        assert ts.review_cycles == 0
        assert ts.accumulated_cost_usd == 0.0
        assert ts.accumulated_tokens_in == 0
        assert ts.accumulated_tokens_out == 0
        assert ts.accumulated_duration_ms == 0

    def test_with_optional_fields(self) -> None:
        ts = self._make(
            status=StageStatus.COMPLETE,
            pr_number=42,
            comment_id="cmt-999",
            review_cycles=2,
            accumulated_cost_usd=1.23,
            accumulated_tokens_in=1000,
            accumulated_tokens_out=500,
            accumulated_duration_ms=30000,
        )
        assert ts.status is StageStatus.COMPLETE
        assert ts.pr_number == 42
        assert ts.comment_id == "cmt-999"
        assert ts.review_cycles == 2
        assert ts.accumulated_cost_usd == pytest.approx(1.23)
        assert ts.accumulated_tokens_in == 1000
        assert ts.accumulated_tokens_out == 500
        assert ts.accumulated_duration_ms == 30000

    def test_json_roundtrip(self) -> None:
        ts = self._make(
            status=StageStatus.QUESTIONS,
            pr_number=7,
            review_cycles=1,
            accumulated_cost_usd=0.05,
        )
        restored = TicketState.model_validate_json(ts.model_dump_json())
        assert restored.stage is StageName.SPEC
        assert restored.status is StageStatus.QUESTIONS
        assert restored.pr_number == 7
        assert restored.review_cycles == 1
        assert restored.accumulated_cost_usd == pytest.approx(0.05)
        assert restored.branch == "feature/TEST-1"
        assert restored.stage_run_id == "run-abc123"

    def test_base_branch_override(self) -> None:
        ts = self._make(base_branch="develop")
        assert ts.base_branch == "develop"


@pytest.mark.unit
class TestStageResultExtendedFields:
    def test_new_optional_fields_present(self) -> None:
        r = StageResult.model_validate_json(
            '{"status": "complete", "pr_title": "My PR", "pr_summary": "Summary",'
            ' "ticket_summary": "Ticket done", "spec_path": "docs/spec.md",'
            ' "plan_path": "docs/plan.md", "questions": ["Q1?", "Q2?"]}'
        )
        assert r.status is StageStatus.COMPLETE
        assert r.pr_title == "My PR"
        assert r.pr_summary == "Summary"
        assert r.ticket_summary == "Ticket done"
        assert r.spec_path == "docs/spec.md"
        assert r.plan_path == "docs/plan.md"
        assert r.questions == ["Q1?", "Q2?"]

    def test_backward_compat_no_new_fields(self) -> None:
        r = StageResult.model_validate_json('{"status": "complete"}')
        assert r.status is StageStatus.COMPLETE
        assert r.pr_title is None
        assert r.pr_summary is None
        assert r.ticket_summary is None
        assert r.spec_path is None
        assert r.plan_path is None
        assert r.questions is None

    def test_extract_result_with_new_fields(self) -> None:
        output = (
            "Done.\n\n```a2sdlc\n"
            '{"status": "complete", "pr_title": "feat: my feature"}\n'
            "```\n"
        )
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.COMPLETE
        assert result.pr_title == "feat: my feature"

    def test_extract_result_backward_compat(self) -> None:
        output = '```a2sdlc\n{"status": "questions"}\n```'
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.QUESTIONS
        assert result.questions is None
