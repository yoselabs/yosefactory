"""Tests for a2sdlc.verifier — pure routing logic + action execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.config import ProjectConfig
from a2sdlc.models import StageAction
from a2sdlc.runner import RunResult
from a2sdlc.verifier import execute_action, resolve_action, verify_and_act


# ── Helpers ──────────────────────────────────────────────────────────


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


def _project(auto_merge: bool = False) -> ProjectConfig:
    return ProjectConfig(auto_merge=auto_merge)


# ── resolve_action (pure, no mocks needed) ───────────────────────────


@pytest.mark.unit
class TestResolveAction:
    def test_error_result(self) -> None:
        action = resolve_action("spec", _result("", success=False), _project())
        assert "🚨" in action.comment
        assert "Error" in action.comment
        assert action.transition_to is None
        assert action.write_state is None

    def test_no_status_block(self) -> None:
        action = resolve_action("spec", _result("No block here"), _project())
        assert "⚠️" in action.comment
        assert "No status block" in action.comment

    def test_spec_complete(self) -> None:
        output = 'Spec done.\n\n```a2sdlc\n{"status": "complete"}\n```'
        action = resolve_action("spec", _result(output), _project())
        assert "Spec done." in action.comment
        assert action.write_state == ("spec", "complete")
        assert action.transition_to is None

    def test_spec_questions(self) -> None:
        output = '1. What auth?\n\n```a2sdlc\n{"status": "questions"}\n```'
        action = resolve_action("spec", _result(output), _project())
        assert "What auth?" in action.comment
        assert action.transition_to == "needs-input"
        assert action.write_state is None

    def test_implement_complete(self) -> None:
        output = 'PR #15 created.\n\n```a2sdlc\n{"status": "complete"}\n```'
        action = resolve_action("implement", _result(output), _project())
        assert "PR #15" in action.comment
        assert action.write_state == ("implement", "complete")

    def test_implement_questions(self) -> None:
        output = 'Plan gap found.\n\n```a2sdlc\n{"status": "questions"}\n```'
        action = resolve_action("implement", _result(output), _project())
        assert action.transition_to == "needs-input"

    def test_review_approved(self) -> None:
        output = 'Looks good.\n\n```a2sdlc\n{"status": "approved"}\n```'
        action = resolve_action("review", _result(output), _project())
        assert "Looks good." in action.comment
        assert action.transition_to is None
        assert action.merge_pr is None  # auto_merge=False

    def test_review_changes_requested(self) -> None:
        output = 'SQL injection.\n\n```a2sdlc\n{"status": "changes_requested"}\n```'
        action = resolve_action("review", _result(output), _project())
        assert action.transition_to == "needs-fix"

    def test_unexpected_stage_status(self) -> None:
        output = 'Weird.\n\n```a2sdlc\n{"status": "approved"}\n```'
        action = resolve_action("spec", _result(output), _project())
        assert "⚠️" in action.comment
        assert "Unexpected" in action.comment

    def test_cost_footer_always_present(self) -> None:
        output = 'Done.\n\n```a2sdlc\n{"status": "complete"}\n```'
        action = resolve_action("spec", _result(output), _project())
        assert "Tokens:" in action.comment
        assert "$0.05" in action.comment
        assert "30s" in action.comment

    def test_cost_footer_on_error(self) -> None:
        action = resolve_action("spec", _result("", success=False), _project())
        assert "$0.05" in action.comment


# ── execute_action ───────────────────────────────────────────────────


@pytest.mark.unit
class TestExecuteAction:
    def test_post_with_comment_id(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        action = StageAction(comment="Hello")
        execute_action(action, "PROJ-1", tickets, code, comment_id="c1")
        tickets.update_comment.assert_called_once_with("PROJ-1", "c1", "Hello")
        tickets.create_comment.assert_not_called()

    def test_post_without_comment_id(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        action = StageAction(comment="Hello")
        execute_action(action, "PROJ-1", tickets, code)
        tickets.create_comment.assert_called_once_with("PROJ-1", "Hello")

    def test_transition(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        action = StageAction(comment="Q", transition_to="needs-input")
        execute_action(action, "PROJ-1", tickets, code)
        tickets.transition.assert_called_once_with("PROJ-1", "needs-input")

    def test_no_transition_when_none(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        action = StageAction(comment="Done")
        execute_action(action, "PROJ-1", tickets, code)
        tickets.transition.assert_not_called()

    def test_merge_pr(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        action = StageAction(comment="Approved", merge_pr=42)
        execute_action(action, "42", tickets, code)
        code.merge_pr.assert_called_once_with(42)

    def test_no_merge_when_none(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        action = StageAction(comment="Approved")
        execute_action(action, "42", tickets, code)
        code.merge_pr.assert_not_called()


# ── verify_and_act (integration of resolve + execute) ────────────────


@pytest.mark.unit
class TestVerifyAndAct:
    def test_spec_complete_flow(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Spec done.\n\n```a2sdlc\n{"status": "complete"}\n```'
        verify_and_act(
            "spec", _result(output), "PROJ-1", tickets, code, _project(), "c1"
        )
        tickets.update_comment.assert_called_once()
        body = tickets.update_comment.call_args[0][2]
        assert "Spec done." in body

    def test_review_approved_auto_merge(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Good.\n\n```a2sdlc\n{"status": "approved"}\n```'
        verify_and_act(
            "review",
            _result(output),
            "42",
            tickets,
            code,
            _project(auto_merge=True),
            "c1",
            pr_number=42,
        )
        code.merge_pr.assert_called_once_with(42)

    def test_review_approved_no_auto_merge(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Good.\n\n```a2sdlc\n{"status": "approved"}\n```'
        verify_and_act("review", _result(output), "42", tickets, code, _project(), "c1")
        code.merge_pr.assert_not_called()

    def test_review_approved_no_pr_number(self) -> None:
        tickets = MagicMock()
        code = MagicMock()
        output = 'Good.\n\n```a2sdlc\n{"status": "approved"}\n```'
        verify_and_act(
            "review",
            _result(output),
            "PROJ-1",
            tickets,
            code,
            _project(auto_merge=True),
            "c1",
        )
        code.merge_pr.assert_not_called()  # no pr_number passed
