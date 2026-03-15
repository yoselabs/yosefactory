"""Tests for GitHubTicketAdapter — parse_event, label management, PR ops."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.adapters.github import GitHubTicketAdapter
from a2sdlc.exceptions import SkipEvent
from a2sdlc.models import StageName


@pytest.mark.unit
class TestParseEvent:
    def _write_event(self, tmp_path: Path, event: dict) -> str:
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event))
        return str(event_file)

    def test_agent_label_triggers_spec(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "agent"},
                "issue": {"number": 15, "labels": [{"name": "agent"}]},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            result = adapter.parse_event()
        assert result.stage == StageName.SPEC
        assert result.key == "15"

    def test_stage_label_triggers_stage(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "stage:implement"},
                "issue": {"number": 15, "labels": [{"name": "stage:implement"}]},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            result = adapter.parse_event()
        assert result.stage == StageName.IMPLEMENT
        assert result.key == "15"

    def test_proceed_label_triggers_implement(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "proceed"},
                "issue": {"number": 15, "labels": [{"name": "proceed"}]},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            result = adapter.parse_event()
        assert result.stage == StageName.IMPLEMENT

    def test_unknown_label_raises_skip(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "bug"},
                "issue": {"number": 15, "labels": [{"name": "bug"}]},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            with pytest.raises(SkipEvent, match="not a stage label"):
                adapter.parse_event()

    def test_bot_label_event_allowed(self, tmp_path: Path) -> None:
        """Bot label events are intentional (stage chain). Should NOT skip."""
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "stage:spec"},
                "issue": {"number": 15, "labels": [{"name": "stage:spec"}]},
                "sender": {"type": "Bot"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            result = adapter.parse_event()
        assert result.stage == StageName.SPEC

    def test_bot_comment_raises_skip(self, tmp_path: Path) -> None:
        """Bot comments should be skipped (prevents infinite loops)."""
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "issue": {"number": 15, "labels": [{"name": "needs-input"}]},
                "sender": {"type": "Bot"},
                "comment": {"body": "bot comment"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issue_comment"},
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            with pytest.raises(SkipEvent, match="bot"):
                adapter.parse_event()

    def test_issue_comment_with_needs_input(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "issue": {"number": 15, "labels": [{"name": "needs-input"}]},
                "sender": {"type": "User"},
                "comment": {"body": "Here are my answers"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issue_comment"},
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            result = adapter.parse_event()
        assert result.is_resume is True
        assert result.key == "15"
        assert result.stage == StageName.SPEC  # default resume stage

    def test_issue_comment_without_needs_input_skips(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "issue": {"number": 15, "labels": [{"name": "agent"}]},
                "sender": {"type": "User"},
                "comment": {"body": "Just a comment"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issue_comment"},
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            with pytest.raises(SkipEvent, match="needs-input"):
                adapter.parse_event()

    def test_pr_labeled_review(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "stage:review"},
                "pull_request": {"number": 42},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "pull_request"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            result = adapter.parse_event()
        assert result.stage == StageName.REVIEW
        assert result.pr_number == 42
        assert result.key == "42"

    def test_issue_labeled_review_resolves_pr(self, tmp_path: Path) -> None:
        """stage:review on an issue should look up the PR from agent branch."""
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "stage:review"},
                "issue": {"number": 16, "labels": [{"name": "stage:review"}]},
                "sender": {"type": "User"},
            },
        )
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_repo.get_pulls.return_value = [mock_pr]
        adapter._repo = mock_repo

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            result = adapter.parse_event()

        assert result.stage == StageName.REVIEW
        assert result.pr_number == 42
        assert result.key == "16"
        mock_repo.get_pulls.assert_called_once_with(state="open", head="agent/16")

    def test_issue_labeled_review_no_pr_raises_skip(self, tmp_path: Path) -> None:
        """stage:review on an issue with no PR should skip."""
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "stage:review"},
                "issue": {"number": 16, "labels": [{"name": "stage:review"}]},
                "sender": {"type": "User"},
            },
        )
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_repo.get_pulls.return_value = []
        adapter._repo = mock_repo

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            with pytest.raises(SkipEvent, match="no PR found"):
                adapter.parse_event()

    def test_unknown_event_name_raises_skip(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "opened",
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "push"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            with pytest.raises(SkipEvent):
                adapter.parse_event()

    def test_issues_unlabeled_raises_skip(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "unlabeled",
                "label": {"name": "agent"},
                "issue": {"number": 15, "labels": []},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
            with pytest.raises(SkipEvent, match="action"):
                adapter.parse_event()


@pytest.mark.unit
class TestSetStageLabel:
    def test_removes_old_sets_new(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
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
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
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
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
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
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_blocked("15", "merge conflict")

        mock_issue.add_to_labels.assert_called_once_with("stage:blocked")
        mock_issue.create_comment.assert_called_once()
        body = mock_issue.create_comment.call_args[0][0]
        assert "merge conflict" in body


@pytest.mark.unit
class TestPostComment:
    def test_returns_comment_id(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_comment = MagicMock()
        mock_comment.id = 99
        mock_issue.create_comment.return_value = mock_comment
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.post_comment("15", "hello")

        mock_issue.create_comment.assert_called_once_with("hello")
        assert result == "99"


@pytest.mark.unit
class TestUpdateComment:
    def test_edits_comment(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_comment = MagicMock()
        mock_issue.get_comment.return_value = mock_comment
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.update_comment("15", "99", "updated body")

        mock_repo.get_issue.assert_called_once_with(15)
        mock_issue.get_comment.assert_called_once_with(99)
        mock_comment.edit.assert_called_once_with("updated body")


@pytest.mark.unit
class TestGetLabels:
    def test_returns_label_names(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
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
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.body = "Issue description"
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.get_ticket("15")

        assert result == "Issue description"

    def test_pr_returns_summary(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.title = "My PR"
        mock_pr.body = "PR description"
        mock_file = MagicMock()
        mock_file.filename = "src/foo.py"
        mock_pr.get_files.return_value = [mock_file]
        mock_repo.get_pull.return_value = mock_pr
        mock_repo.get_issue.side_effect = Exception("should not be called for PR")
        adapter._repo = mock_repo

        result = adapter.get_ticket("pr:42")

        assert "My PR" in result
        assert "PR description" in result
        assert "src/foo.py" in result


@pytest.mark.unit
class TestPostReview:
    def test_approve(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_review(42, "LGTM", "APPROVE")

        mock_repo.get_pull.assert_called_once_with(42)
        mock_pr.create_review.assert_called_once_with(body="LGTM", event="APPROVE")


@pytest.mark.unit
class TestMergePr:
    def test_squash_merge(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.merge_pr(42)

        mock_repo.get_pull.assert_called_once_with(42)
        mock_pr.merge.assert_called_once_with(merge_method="squash")

    def test_merge_method_passed(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.merge_pr(42, method="merge")

        mock_pr.merge.assert_called_once_with(merge_method="merge")


@pytest.mark.unit
class TestGetPrForBranch:
    def test_finds_pr(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_repo.get_pulls.return_value = [mock_pr]
        adapter._repo = mock_repo

        assert adapter.get_pr_for_branch("agent/15") == 42

    def test_no_pr_returns_none(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_repo.get_pulls.return_value = []
        adapter._repo = mock_repo

        assert adapter.get_pr_for_branch("agent/15") is None

    def test_queries_with_head_branch(self) -> None:
        adapter = GitHubTicketAdapter.__new__(GitHubTicketAdapter)
        mock_repo = MagicMock()
        mock_repo.get_pulls.return_value = []
        adapter._repo = mock_repo

        adapter.get_pr_for_branch("agent/15")

        mock_repo.get_pulls.assert_called_once_with(state="open", head="agent/15")
