"""Tests for a2sdlc.domain.models — Pydantic models and structured output parsing."""

from __future__ import annotations

from typing import Any

import pytest

from a2sdlc.domain.models import (
    ChildOutcome,
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
        assert cfg.spec is GateMode.AUTO

    def test_has_no_review_field(self) -> None:
        cfg = GateConfig()
        assert not hasattr(cfg, "review")

    def test_override_merge(self) -> None:
        cfg = GateConfig(merge=GateMode.AUTO)
        assert cfg.merge is GateMode.AUTO
        assert cfg.spec is GateMode.AUTO

    def test_override_spec(self) -> None:
        cfg = GateConfig(spec=GateMode.HUMAN)
        assert cfg.spec is GateMode.HUMAN
        assert cfg.merge is GateMode.HUMAN

    def test_roundtrip(self) -> None:
        cfg = GateConfig(merge=GateMode.AUTO, spec=GateMode.HUMAN)
        restored = GateConfig.model_validate_json(cfg.model_dump_json())
        assert restored.merge is GateMode.AUTO
        assert restored.spec is GateMode.HUMAN


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
        assert ts.review_cycles == 0
        assert ts.accumulated_cost_usd == 0.0
        assert ts.accumulated_tokens_in == 0
        assert ts.accumulated_tokens_out == 0
        assert ts.accumulated_duration_ms == 0

    def test_with_optional_fields(self) -> None:
        ts = self._make(
            status=StageStatus.COMPLETE,
            pr_number=42,
            review_cycles=2,
            accumulated_cost_usd=1.23,
            accumulated_tokens_in=1000,
            accumulated_tokens_out=500,
            accumulated_duration_ms=30000,
        )
        assert ts.status is StageStatus.COMPLETE
        assert ts.pr_number == 42
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
class TestChildOutcomeStub:
    """ChildOutcome is a reserved placeholder for N5 (ADR-0005)."""

    def test_empty_construction(self) -> None:
        # No required fields — N5 will add them.
        outcome = ChildOutcome()
        assert outcome.model_dump() == {}

    def test_round_trip_preserves_unknown_fields(self) -> None:
        # extra='allow' so a future schema addition survives round-trip
        # when an older reader touches a newer document.
        raw = '{"findings": "edge case X missed", "severity": 2}'
        outcome = ChildOutcome.model_validate_json(raw)
        restored = ChildOutcome.model_validate_json(outcome.model_dump_json())
        assert restored.model_dump() == {
            "findings": "edge case X missed",
            "severity": 2,
        }


@pytest.mark.unit
class TestTicketStateV2Schema:
    """ADR-0005 — TicketState v2 schema, storage invariants."""

    def _make(self, **kwargs: Any) -> TicketState:
        defaults: dict[str, Any] = {
            "stage": StageName.SPEC,
            "branch": "a2sdlc/TEST-1",
            "stage_run_id": "run-abc",
            "last_updated": "2026-04-24T10:00:00Z",
        }
        defaults.update(kwargs)
        return TicketState(**defaults)

    def test_schema_version_defaults_to_2(self) -> None:
        ts = self._make()
        assert ts.schema_version == 2

    def test_n2_fields_default_empty(self) -> None:
        ts = self._make()
        assert ts.parent_key is None
        assert ts.children == []

    def test_n5_placeholder_fields_default_empty(self) -> None:
        ts = self._make()
        assert ts.child_outcomes == {}
        assert ts.revisions == 0

    def test_observability_fields_default(self) -> None:
        ts = self._make()
        assert ts.engine_version == ""
        assert ts.workflow_name == "default"

    def test_rate_limited_until_defaults_none(self) -> None:
        ts = self._make()
        assert ts.rate_limited_until is None

    def test_v2_round_trip_with_all_fields(self) -> None:
        ts = self._make(
            parent_key="EPIC-1",
            children=["TICK-1", "TICK-2"],
            child_outcomes={"TICK-1": ChildOutcome()},
            revisions=1,
            engine_version="0.1.0+abc123",
            workflow_name="review-only",
            rate_limited_until="2026-04-24T11:00:00Z",
        )
        restored = TicketState.model_validate_json(ts.model_dump_json())
        assert restored.schema_version == 2
        assert restored.parent_key == "EPIC-1"
        assert restored.children == ["TICK-1", "TICK-2"]
        assert "TICK-1" in restored.child_outcomes
        assert restored.revisions == 1
        assert restored.engine_version == "0.1.0+abc123"
        assert restored.workflow_name == "review-only"
        assert restored.rate_limited_until == "2026-04-24T11:00:00Z"

    def test_unknown_fields_preserved_on_round_trip(self) -> None:
        # Forward-compat: a v3 field in the JSON must survive round-trip
        # through a v2 reader. Protects against the surprise that broke
        # ``base_branch`` before ADR-0005.
        raw = (
            '{"stage":"spec","branch":"a2sdlc/X","stage_run_id":"r",'
            '"last_updated":"2026-04-24T00:00:00Z",'
            '"future_v3_field":"preserve-me"}'
        )
        ts = TicketState.model_validate_json(raw)
        dumped = ts.model_dump()
        assert dumped.get("future_v3_field") == "preserve-me"

    def test_v1_input_without_schema_version_accepted(self) -> None:
        # The Pydantic model has a default. Migration routing lives in
        # ``session/state_migrations.py``; at the model level, a v1-shape
        # document (no schema_version) simply defaults to v2.
        raw = (
            '{"stage":"spec","branch":"a2sdlc/X","stage_run_id":"r",'
            '"last_updated":"2026-04-24T00:00:00Z"}'
        )
        ts = TicketState.model_validate_json(raw)
        assert ts.schema_version == 2


@pytest.mark.unit
class TestStageResultCleanShape:
    """StageResult has only status, output, and questions — no stage-specific fields."""

    def test_has_output_field(self) -> None:
        r = StageResult(status=StageStatus.COMPLETE, output="Implementation done.")
        assert r.output == "Implementation done."

    def test_output_defaults_to_empty_string(self) -> None:
        r = StageResult(status=StageStatus.COMPLETE)
        assert r.output == ""

    def test_no_pr_title_field(self) -> None:
        assert not hasattr(StageResult.model_fields, "pr_title")
        r = StageResult(status=StageStatus.COMPLETE)
        assert not hasattr(r, "pr_title")

    def test_no_pr_summary_field(self) -> None:
        assert not hasattr(StageResult.model_fields, "pr_summary")

    def test_no_ticket_summary_field(self) -> None:
        assert not hasattr(StageResult.model_fields, "ticket_summary")

    def test_no_spec_path_field(self) -> None:
        assert not hasattr(StageResult.model_fields, "spec_path")

    def test_no_plan_path_field(self) -> None:
        assert not hasattr(StageResult.model_fields, "plan_path")

    def test_no_questions_field(self) -> None:
        assert "questions" not in StageResult.model_fields

    def test_parse_with_output(self) -> None:
        r = StageResult.model_validate_json(
            '{"status": "complete", "output": "Created PR with drag and drop."}'
        )
        assert r.status is StageStatus.COMPLETE
        assert r.output == "Created PR with drag and drop."

    def test_extract_result_with_output(self) -> None:
        output = (
            "Done.\n\n```a2sdlc\n"
            '{"status": "complete", "output": "Implementation done."}\n'
            "```\n"
        )
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.COMPLETE
        assert result.output == "Implementation done."

    def test_extract_result_questions_status(self) -> None:
        output = '```a2sdlc\n{"status": "questions"}\n```'
        result = extract_result(output)
        assert result is not None
        assert result.status is StageStatus.QUESTIONS
