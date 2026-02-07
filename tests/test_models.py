"""Tests for a2sdlc.models — Pydantic models and structured output parsing."""

from __future__ import annotations

import pytest

from a2sdlc.models import (
    BranchState,
    StageResult,
    StageStatus,
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
            stage="spec", status="complete", last_updated="2026-04-05T12:00:00Z"
        )
        dumped = state.model_dump_json()
        restored = BranchState.model_validate_json(dumped)
        assert restored.stage == "spec"
        assert restored.status == "complete"


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
