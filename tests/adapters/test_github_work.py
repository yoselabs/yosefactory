"""Tests for GitHub WorkAdapter — labels, comments, ticket access, branch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.github import GitHubWorkAdapter
from a2sdlc.models import StageName


# ── Helpers ──────────────────────────────────────────────────────────


def _make_work_adapter(trigger_mention: str = "@a2sdlc") -> GitHubWorkAdapter:
    """Create a GitHubWorkAdapter with a mock repo."""
    return GitHubWorkAdapter(repo=MagicMock(), trigger_mention=trigger_mention)


# ── WorkAdapter: labels ──────────────────────────────────────────────


@pytest.mark.unit
class TestSetStageLabel:
    def test_removes_old_sets_new(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        old_label = MagicMock()
        old_label.name = "stage:spec"
        bug_label = MagicMock()
        bug_label.name = "bug"
        mock_issue.labels = [old_label, bug_label]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_stage_label("15", StageName.IMPLEMENT)

        mock_issue.remove_from_labels.assert_called_once_with(old_label)
        mock_issue.add_to_labels.assert_called_once_with("stage:implement")

    def test_no_old_stage_labels(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        bug_label = MagicMock()
        bug_label.name = "bug"
        mock_issue.labels = [bug_label]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_stage_label("15", StageName.SPEC)

        mock_issue.remove_from_labels.assert_not_called()
        mock_issue.add_to_labels.assert_called_once_with("stage:spec")


@pytest.mark.unit
class TestSetDoneLabel:
    def test_adds_done_label(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.labels = []
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_done_label("15")

        mock_issue.add_to_labels.assert_called_once_with("stage:done")


@pytest.mark.unit
class TestSetBlocked:
    def test_adds_label_and_comment(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_blocked("15", "merge conflict")

        mock_issue.add_to_labels.assert_called_once_with("stage:blocked")
        mock_issue.create_comment.assert_called_once()
        body = mock_issue.create_comment.call_args[0][0]
        assert "merge conflict" in body


# ── WorkAdapter: comments ────────────────────────────────────────────


@pytest.mark.unit
class TestBeginComment:
    def test_returns_comment_id(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_comment = MagicMock()
        mock_comment.id = 99
        mock_issue.create_comment.return_value = mock_comment
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.begin_comment("15")

        mock_issue.create_comment.assert_called_once()
        assert result == "99"


@pytest.mark.unit
class TestUpdateProgress:
    def test_patches_comment_by_id(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_repo.url = "https://api.github.com/repos/owner/repo"
        adapter._repo = mock_repo

        adapter.update_progress("99", "new body")

        mock_repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PATCH",
            "https://api.github.com/repos/owner/repo/issues/comments/99",
            input={"body": "new body"},
        )


@pytest.mark.unit
class TestFinalizeComment:
    def test_delegates_to_update_progress(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_repo.url = "https://api.github.com/repos/owner/repo"
        adapter._repo = mock_repo

        adapter.finalize_comment("99", "final body")

        mock_repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PATCH",
            "https://api.github.com/repos/owner/repo/issues/comments/99",
            input={"body": "final body"},
        )


# ── WorkAdapter: ticket access ───────────────────────────────────────


@pytest.mark.unit
class TestGetLabels:
    def test_returns_label_names(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        lbl1 = MagicMock()
        lbl1.name = "agent"
        lbl2 = MagicMock()
        lbl2.name = "stage:spec"
        mock_issue.labels = [lbl1, lbl2]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.get_labels("15")

        assert result == ["agent", "stage:spec"]


@pytest.mark.unit
class TestGetTicket:
    def test_issue_returns_body(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.body = "Issue description"
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.get_ticket("15")

        assert result == "Issue description"


# ── WorkAdapter: format_branch ───────────────────────────────────────


@pytest.mark.unit
class TestFormatBranch:
    def test_returns_agent_prefix(self) -> None:
        adapter = _make_work_adapter()
        assert adapter.format_branch("15") == "agent/15"
        assert adapter.format_branch("PROJ-42") == "agent/PROJ-42"


# ── Feedback stubs (not yet implemented) ────────────────────────────


@pytest.mark.unit
class TestFeedbackStubs:
    def test_collect_issue_feedback_not_implemented(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_work_adapter()
        with pytest.raises(NotImplementedError):
            adapter.collect_issue_feedback("15", datetime.now(timezone.utc))

    def test_find_last_handover_not_implemented(self) -> None:
        adapter = _make_work_adapter()
        with pytest.raises(NotImplementedError):
            adapter.find_last_handover("15")
