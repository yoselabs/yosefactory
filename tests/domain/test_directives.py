"""Tests for a2sdlc.domain.directives — ticket directive parsing."""

from __future__ import annotations

import pytest

from a2sdlc.domain.directives import (
    TicketDirectives,
    merge_directives,
    parse_directives,
    parse_label_directives,
)
from a2sdlc.domain.models import GateMode


@pytest.mark.unit
class TestParseDirectivesNoDirectives:
    def test_no_directives_returns_empty_and_unchanged_body(self) -> None:
        body = "This is a ticket description.\n\nWith multiple paragraphs."
        directives, cleaned = parse_directives(body)
        assert directives == TicketDirectives()
        assert cleaned == body

    def test_empty_body_no_crash(self) -> None:
        directives, cleaned = parse_directives("")
        assert directives == TicketDirectives()
        assert cleaned == ""


@pytest.mark.unit
class TestParseDirectivesBase:
    def test_single_base_directive(self) -> None:
        body = "[a2sdlc base=feature/my-branch]\nDo the thing."
        directives, cleaned = parse_directives(body)
        assert directives.base == "feature/my-branch"
        assert "a2sdlc" not in cleaned
        assert "Do the thing." in cleaned

    def test_base_directive_stripped_from_body(self) -> None:
        body = "Before.\n[a2sdlc base=feature/x]\nAfter."
        directives, cleaned = parse_directives(body)
        assert directives.base == "feature/x"
        assert cleaned == "Before.\nAfter."


@pytest.mark.unit
class TestParseDirectivesGate:
    def test_gate_merge_human(self) -> None:
        body = "[a2sdlc gate:merge=human]"
        directives, _ = parse_directives(body)
        assert directives.gate_merge is GateMode.HUMAN

    def test_gate_spec_auto(self) -> None:
        body = "[a2sdlc gate:spec=auto]"
        directives, _ = parse_directives(body)
        assert directives.gate_spec is GateMode.AUTO

    def test_gate_spec_human(self) -> None:
        body = "[a2sdlc gate:spec=human]"
        directives, _ = parse_directives(body)
        assert directives.gate_spec is GateMode.HUMAN


@pytest.mark.unit
class TestParseDirectivesMultipleKeys:
    def test_multiple_keys_on_one_line(self) -> None:
        body = "[a2sdlc base=feature/x gate:merge=human model=opus]"
        directives, cleaned = parse_directives(body)
        assert directives.base == "feature/x"
        assert directives.gate_merge is GateMode.HUMAN
        assert directives.model == "opus"
        assert cleaned == ""

    def test_model_directive(self) -> None:
        body = "[a2sdlc model=sonnet]"
        directives, _ = parse_directives(body)
        assert directives.model == "sonnet"


@pytest.mark.unit
class TestParseDirectivesMultipleLines:
    def test_two_directive_lines_merged(self) -> None:
        body = "[a2sdlc base=feature/x]\n[a2sdlc gate:merge=human]\nDo the thing."
        directives, cleaned = parse_directives(body)
        assert directives.base == "feature/x"
        assert directives.gate_merge is GateMode.HUMAN
        assert "Do the thing." in cleaned
        assert "a2sdlc" not in cleaned

    def test_later_line_overrides_earlier(self) -> None:
        body = "[a2sdlc base=feature/a]\n[a2sdlc base=feature/b]"
        directives, _ = parse_directives(body)
        assert directives.base == "feature/b"


@pytest.mark.unit
class TestParseDirectivesMalformed:
    def test_empty_brackets_ignored(self) -> None:
        body = "[a2sdlc]\nSome text."
        directives, cleaned = parse_directives(body)
        assert directives == TicketDirectives()
        assert "Some text." in cleaned

    def test_invalid_gate_value_ignored(self) -> None:
        body = "[a2sdlc gate:merge=bogus]\nSome text."
        directives, cleaned = parse_directives(body)
        assert directives.gate_merge is None
        assert "Some text." in cleaned

    def test_unknown_key_ignored(self) -> None:
        body = "[a2sdlc unknown_key=foo base=feature/x]"
        directives, _ = parse_directives(body)
        assert directives.base == "feature/x"

    def test_no_crash_on_malformed(self) -> None:
        body = "[a2sdlc ===]\nOk text."
        # Should not raise
        directives, cleaned = parse_directives(body)
        assert "Ok text." in cleaned


@pytest.mark.unit
class TestParseDirectivesBodyPreserved:
    def test_body_content_preserved_after_strip(self) -> None:
        body = (
            "[a2sdlc base=feature/x]\n"
            "\n"
            "## Summary\n"
            "\n"
            "This ticket is about doing X.\n"
            "\n"
            "## Details\n"
            "\n"
            "More information here."
        )
        directives, cleaned = parse_directives(body)
        assert directives.base == "feature/x"
        assert "## Summary" in cleaned
        assert "This ticket is about doing X." in cleaned
        assert "## Details" in cleaned
        assert "[a2sdlc" not in cleaned

    def test_whitespace_trimmed_from_cleaned_body(self) -> None:
        body = "[a2sdlc base=feature/x]\n\nActual content."
        _, cleaned = parse_directives(body)
        assert not cleaned.startswith("\n")
        assert not cleaned.endswith("\n")


@pytest.mark.unit
class TestParseLabelDirectives:
    def test_no_gate_labels_returns_empty(self) -> None:
        directives = parse_label_directives(["agent", "stage:spec"])
        assert directives == TicketDirectives()

    def test_gate_merge_human_label(self) -> None:
        directives = parse_label_directives(["agent", "gate:merge:human"])
        assert directives.gate_merge is GateMode.HUMAN

    def test_gate_merge_auto_label(self) -> None:
        directives = parse_label_directives(["gate:merge:auto"])
        assert directives.gate_merge is GateMode.AUTO

    def test_gate_spec_human_label(self) -> None:
        directives = parse_label_directives(["gate:spec:human"])
        assert directives.gate_spec is GateMode.HUMAN

    def test_both_gate_labels(self) -> None:
        directives = parse_label_directives(
            ["gate:merge:human", "gate:spec:auto", "agent"]
        )
        assert directives.gate_merge is GateMode.HUMAN
        assert directives.gate_spec is GateMode.AUTO

    def test_unknown_gate_value_ignored(self) -> None:
        directives = parse_label_directives(["gate:merge:bogus"])
        assert directives.gate_merge is None

    def test_unknown_axis_ignored(self) -> None:
        directives = parse_label_directives(["gate:bogus:human"])
        assert directives.gate_merge is None
        assert directives.gate_spec is None

    def test_partial_match_ignored(self) -> None:
        # Anchored regex — `gate:merge:human-extra` must not match.
        directives = parse_label_directives(["gate:merge:human-extra"])
        assert directives.gate_merge is None

    def test_empty_label_list(self) -> None:
        directives = parse_label_directives([])
        assert directives == TicketDirectives()


@pytest.mark.unit
class TestMergeDirectives:
    def test_label_overrides_body_for_gate_merge(self) -> None:
        body = TicketDirectives(gate_merge=GateMode.AUTO, base="develop")
        label = TicketDirectives(gate_merge=GateMode.HUMAN)
        merged = merge_directives(label, body)
        assert merged.gate_merge is GateMode.HUMAN
        # Body-only fields preserved.
        assert merged.base == "develop"

    def test_label_authoritative_for_gate_spec(self) -> None:
        body = TicketDirectives(gate_spec=GateMode.AUTO)
        label = TicketDirectives(gate_spec=GateMode.HUMAN)
        merged = merge_directives(label, body)
        assert merged.gate_spec is GateMode.HUMAN

    def test_body_used_when_no_label_present(self) -> None:
        body = TicketDirectives(gate_merge=GateMode.HUMAN, base="develop")
        label = TicketDirectives()
        merged = merge_directives(label, body)
        assert merged.gate_merge is GateMode.HUMAN
        assert merged.base == "develop"

    def test_neither_set_yields_none(self) -> None:
        merged = merge_directives(TicketDirectives(), TicketDirectives())
        assert merged.gate_merge is None
        assert merged.gate_spec is None
        assert merged.base is None

    def test_base_and_model_only_from_body(self) -> None:
        body = TicketDirectives(base="feature/x", model="opus")
        label = TicketDirectives(gate_merge=GateMode.HUMAN)  # no base/model on labels
        merged = merge_directives(label, body)
        assert merged.base == "feature/x"
        assert merged.model == "opus"
        assert merged.gate_merge is GateMode.HUMAN
