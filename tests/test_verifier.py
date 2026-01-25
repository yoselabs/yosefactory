"""Tests for a2sdlc.verifier — artifact extraction, marker checks, post-conditions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.verifier import check_markers, extract_artifact, verify_and_act


# ── extract_artifact ────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractArtifact:
    def test_extract_prd_artifact(self) -> None:
        output = (
            "Some intro text\n"
            "## [A2SDLC:PRD]\n"
            "This is the PRD content.\n"
            "It has multiple lines.\n"
        )
        result = extract_artifact(output, "PRD")
        assert result == "This is the PRD content.\nIt has multiple lines."

    def test_extract_questions(self) -> None:
        output = "## Questions\n1. What is the scope?\n2. Who is the owner?\n"
        result = extract_artifact(output, "Questions")
        assert result == "1. What is the scope?\n2. Who is the owner?"

    def test_extract_artifact_not_found(self) -> None:
        output = "Some text without any markers.\n## Other heading\nStuff."
        result = extract_artifact(output, "PRD")
        assert result == ""

    def test_extract_artifact_stops_at_next_heading(self) -> None:
        output = (
            "## [A2SDLC:PRD]\nPRD content here.\n## [A2SDLC:PLAN]\nPlan content here.\n"
        )
        result = extract_artifact(output, "PRD")
        assert result == "PRD content here."


# ── check_markers ──────────────────────────────────────────────────


@pytest.mark.unit
class TestCheckMarkers:
    def test_check_markers_prd(self) -> None:
        output = "## [A2SDLC:PRD]\nContent."
        markers = check_markers(output)
        assert markers["has_prd"] is True
        assert markers["has_questions"] is False
        assert markers["has_plan"] is False
        assert markers["has_review"] is False

    def test_check_markers_questions(self) -> None:
        output = "## Questions\n1. Something?"
        markers = check_markers(output)
        assert markers["has_questions"] is True
        assert markers["has_prd"] is False
        assert markers["has_plan"] is False
        assert markers["has_review"] is False

    def test_check_markers_both(self) -> None:
        output = "## [A2SDLC:PRD]\nPRD.\n## Questions\n1. Q?"
        markers = check_markers(output)
        assert markers["has_prd"] is True
        assert markers["has_questions"] is True


# ── verify_and_act ─────────────────────────────────────────────────


@pytest.mark.unit
class TestVerifyAndAct:
    @staticmethod
    def _make_result(success: bool, output: str) -> dict:
        return {
            "success": success,
            "output": output,
            "error": None if success else "some_error",
            "session_id": "sid-1",
            "raw": {},
        }

    def test_verify_prd_with_questions(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = "## Questions\n1. What is the scope?\n2. Who owns it?"
        result = self._make_result(True, output)

        verify_and_act("prd", result, "PROJ-1", tickets, code)

        tickets.update_comment.assert_called_once()
        call_body = tickets.update_comment.call_args[1].get(
            "body", tickets.update_comment.call_args[0][2]
        )
        assert "❓" in call_body

        tickets.transition.assert_called_once_with("PROJ-1", "needs-input")
        tickets.trigger_next.assert_not_called()

    def test_verify_prd_complete(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = "## [A2SDLC:PRD]\nThe full PRD document."
        result = self._make_result(True, output)

        verify_and_act("prd", result, "PROJ-1", tickets, code)

        tickets.update_comment.assert_called_once()
        call_body = tickets.update_comment.call_args[0][2]
        assert "✅" in call_body

        tickets.transition.assert_called_once_with("PROJ-1", "prd-complete")
        tickets.trigger_next.assert_called_once_with("prd-approved", {"key": "PROJ-1"})

    def test_verify_prd_complete_supervised(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = "## [A2SDLC:PRD]\nThe full PRD document."
        result = self._make_result(True, output)

        verify_and_act("prd", result, "PROJ-1", tickets, code, supervised=True)

        tickets.update_comment.assert_called_once()
        tickets.transition.assert_called_once_with("PROJ-1", "prd-complete")
        tickets.trigger_next.assert_not_called()

    def test_verify_error_result(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        result = self._make_result(False, "")

        verify_and_act("prd", result, "PROJ-1", tickets, code)

        tickets.create_comment.assert_called_once()
        call_body = tickets.create_comment.call_args[0][1]
        assert "error" in call_body.lower() or "Error" in call_body

    def test_verify_prd_no_markers(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = "Some random output without any markers at all."
        result = self._make_result(True, output)

        verify_and_act("prd", result, "PROJ-1", tickets, code)

        tickets.create_comment.assert_called_once()
        call_body = tickets.create_comment.call_args[0][1]
        assert "warning" in call_body.lower() or "⚠" in call_body

    def test_verify_plan_complete(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = "## [A2SDLC:PLAN]\nStep 1: Do the thing."
        result = self._make_result(True, output)

        verify_and_act("plan", result, "PROJ-1", tickets, code)

        tickets.update_comment.assert_called_once()
        call_body = tickets.update_comment.call_args[0][2]
        assert "✅" in call_body

        tickets.transition.assert_called_once_with("PROJ-1", "plan-complete")
        tickets.trigger_next.assert_called_once_with("plan-approved", {"key": "PROJ-1"})

    def test_verify_plan_complete_supervised(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = "## [A2SDLC:PLAN]\nStep 1: Do the thing."
        result = self._make_result(True, output)

        verify_and_act("plan", result, "PROJ-1", tickets, code, supervised=True)

        tickets.trigger_next.assert_not_called()
