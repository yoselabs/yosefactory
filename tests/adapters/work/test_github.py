"""Tests for GitHub WorkAdapter — labels, comments, ticket access, branch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.work.github import GitHubWorkAdapter
from a2sdlc.domain.models import StageName


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

    def test_also_removes_agent_trigger_label(self) -> None:
        """`agent` trigger label should not linger once engine picks up the ticket."""
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        agent_label = MagicMock()
        agent_label.name = "agent"
        mock_issue.labels = [agent_label]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_stage_label("15", StageName.SPEC)

        mock_issue.remove_from_labels.assert_called_once_with(agent_label)
        mock_issue.add_to_labels.assert_called_once_with("stage:spec")

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

    def test_replaces_prior_stage_and_agent_labels(self) -> None:
        """Done must clean up stage:* and the `agent` trigger label."""
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        old_stage = MagicMock()
        old_stage.name = "stage:merge"
        agent_label = MagicMock()
        agent_label.name = "agent"
        unrelated = MagicMock()
        unrelated.name = "bug"
        mock_issue.labels = [old_stage, agent_label, unrelated]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_done_label("15")

        removed = [c.args[0] for c in mock_issue.remove_from_labels.call_args_list]
        assert old_stage in removed
        assert agent_label in removed
        assert unrelated not in removed
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


@pytest.mark.unit
class TestIsTicketActive:
    def test_open_issue_is_active(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.state = "open"
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        assert adapter.is_ticket_active("15") is True

    def test_closed_issue_is_inactive(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.state = "closed"
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        assert adapter.is_ticket_active("15") is False


# ── WorkAdapter: format_branch ───────────────────────────────────────


@pytest.mark.unit
class TestFormatBranch:
    def test_returns_agent_prefix(self) -> None:
        adapter = _make_work_adapter()
        assert adapter.format_branch("15") == "agent/15"
        assert adapter.format_branch("PROJ-42") == "agent/PROJ-42"


# ── Feedback: find_last_handover ────────────────────────────────────


@pytest.mark.unit
class TestWorkFindLastHandover:
    def test_returns_most_recent_handover(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        c1 = MagicMock()
        c1.body = "a2sdlc:spec\nhandover body 1"
        c1.id = 100
        c1.created_at = datetime(2026, 4, 10, tzinfo=timezone.utc)

        c2 = MagicMock()
        c2.body = "just a regular comment"
        c2.id = 101
        c2.created_at = datetime(2026, 4, 11, tzinfo=timezone.utc)

        c3 = MagicMock()
        c3.body = "a2sdlc:implement\nhandover body 2"
        c3.id = 102
        c3.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)

        mock_issue.get_comments.return_value = [c1, c2, c3]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.find_last_handover("15")

        assert result is not None
        assert result.run_id == "102"
        assert result.location == "issue"

    def test_returns_none_when_no_handovers(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        c1 = MagicMock()
        c1.body = "just a comment"
        c1.id = 100
        c1.created_at = MagicMock()

        mock_issue.get_comments.return_value = [c1]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        assert adapter.find_last_handover("15") is None

    def test_returns_none_when_no_comments(self) -> None:
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.get_comments.return_value = []
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        assert adapter.find_last_handover("15") is None


# ── Feedback: collect_issue_feedback ────────────────────────────────


@pytest.mark.unit
class TestCollectIssueFeedback:
    def test_returns_comments_with_trigger_after_since(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_work_adapter(trigger_mention="@a2sdlc")
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        c1 = MagicMock()
        c1.body = "Hey @a2sdlc please look at this"
        c1.id = 200
        c1.user = MagicMock()
        c1.user.login = "alice"
        c1.user.type = "User"
        c1.created_at = datetime(2026, 4, 11, tzinfo=timezone.utc)

        mock_issue.get_comments.return_value = [c1]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.collect_issue_feedback("15", since)

        assert len(result) == 1
        assert result[0].id == "200"
        assert result[0].author == "alice"
        assert result[0].author_type == "human"
        assert result[0].source == "issue_comment"

    def test_excludes_comments_without_trigger(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_work_adapter(trigger_mention="@a2sdlc")
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        c1 = MagicMock()
        c1.body = "Just a normal comment"
        c1.id = 200
        c1.user = MagicMock()
        c1.user.login = "alice"
        c1.user.type = "User"
        c1.created_at = datetime(2026, 4, 11, tzinfo=timezone.utc)

        mock_issue.get_comments.return_value = [c1]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.collect_issue_feedback("15", since)

        assert result == []

    def test_excludes_handover_comments(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_work_adapter(trigger_mention="@a2sdlc")
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        c1 = MagicMock()
        c1.body = "@a2sdlc a2sdlc:spec\nhandover content"
        c1.id = 200
        c1.user = MagicMock()
        c1.user.login = "bot-user"
        c1.user.type = "Bot"
        c1.created_at = datetime(2026, 4, 11, tzinfo=timezone.utc)

        mock_issue.get_comments.return_value = [c1]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.collect_issue_feedback("15", since)

        assert result == []

    def test_bot_author_type(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_work_adapter(trigger_mention="@a2sdlc")
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        c1 = MagicMock()
        c1.body = "Hey @a2sdlc check this"
        c1.id = 200
        c1.user = MagicMock()
        c1.user.login = "some-bot"
        c1.user.type = "Bot"
        c1.created_at = datetime(2026, 4, 11, tzinfo=timezone.utc)

        mock_issue.get_comments.return_value = [c1]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.collect_issue_feedback("15", since)

        assert len(result) == 1
        assert result[0].author_type == "bot"
