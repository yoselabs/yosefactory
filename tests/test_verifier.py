"""Tests for a2sdlc.verifier — Pydantic-based post-condition checks."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.config import ProjectConfig
from a2sdlc.runner import RunResult
from a2sdlc.verifier import verify_and_act


@pytest.mark.unit
class TestVerifyAndAct:
    @staticmethod
    def _result(output: str, success: bool = True) -> RunResult:
        return RunResult(
            success=success,
            output=output,
            error=None if success else "some_error",
            input_tokens=1000,
            output_tokens=500,
            total_cost_usd=0.05,
            duration_ms=30000,
        )

    @staticmethod
    def _project(auto_merge: bool = False) -> ProjectConfig:
        return ProjectConfig(auto_merge=auto_merge)

    def test_spec_complete(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Spec is done.\n\n```a2sdlc\n{"status": "complete"}\n```'
        result = self._result(output)

        verify_and_act(
            "spec", result, "PROJ-1", tickets, code, self._project(), comment_id="c1"
        )

        tickets.update_comment.assert_called_once()
        body = tickets.update_comment.call_args[0][2]
        assert "Spec is done" in body
        assert "Tokens:" in body
        assert "$0.05" in body

    def test_spec_questions(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = '1. What auth?\n2. What DB?\n\n```a2sdlc\n{"status": "questions"}\n```'
        result = self._result(output)

        verify_and_act(
            "spec", result, "PROJ-1", tickets, code, self._project(), comment_id="c1"
        )

        tickets.update_comment.assert_called_once()
        body = tickets.update_comment.call_args[0][2]
        assert "What auth?" in body
        tickets.transition.assert_called_once_with("PROJ-1", "needs-input")

    def test_implement_complete(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'PR created: #15\n\n```a2sdlc\n{"status": "complete"}\n```'
        result = self._result(output)

        verify_and_act(
            "implement",
            result,
            "PROJ-1",
            tickets,
            code,
            self._project(),
            comment_id="c1",
        )

        tickets.update_comment.assert_called_once()
        body = tickets.update_comment.call_args[0][2]
        assert "PR created" in body

    def test_review_approved(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Looks good.\n\n```a2sdlc\n{"status": "approved"}\n```'
        result = self._result(output)

        verify_and_act(
            "review", result, "42", tickets, code, self._project(), comment_id="c1"
        )

        tickets.update_comment.assert_called_once()
        code.merge_pr.assert_not_called()  # auto_merge=False

    def test_review_approved_auto_merge(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Looks good.\n\n```a2sdlc\n{"status": "approved"}\n```'
        result = self._result(output)

        verify_and_act(
            "review",
            result,
            "42",
            tickets,
            code,
            self._project(auto_merge=True),
            comment_id="c1",
        )

        code.merge_pr.assert_called_once_with(42)

    def test_review_changes_requested(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = (
            'SQL injection found.\n\n```a2sdlc\n{"status": "changes_requested"}\n```'
        )
        result = self._result(output)

        verify_and_act(
            "review", result, "42", tickets, code, self._project(), comment_id="c1"
        )

        tickets.transition.assert_called_once_with("42", "needs-fix")

    def test_error_result(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        result = self._result("", success=False)

        verify_and_act("spec", result, "PROJ-1", tickets, code, self._project())

        tickets.create_comment.assert_called_once()
        body = tickets.create_comment.call_args[0][1]
        assert "Error" in body or "🚨" in body

    def test_no_status_block(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = "Some output without any status block."
        result = self._result(output)

        verify_and_act("spec", result, "PROJ-1", tickets, code, self._project())

        tickets.create_comment.assert_called_once()
        body = tickets.create_comment.call_args[0][1]
        assert "⚠️" in body

    def test_cost_footer_in_all_outputs(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Done.\n\n```a2sdlc\n{"status": "complete"}\n```'
        result = self._result(output)

        verify_and_act(
            "spec", result, "PROJ-1", tickets, code, self._project(), comment_id="c1"
        )

        body = tickets.update_comment.call_args[0][2]
        assert "Tokens:" in body
        assert "$0.05" in body
        assert "30s" in body
