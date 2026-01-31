"""Tests for a2sdlc.adapters.jira_tickets — JiraTickets adapter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.adapters.jira_tickets import JiraTickets


@pytest.mark.unit
class TestJiraTickets:
    def setup_method(self) -> None:
        with patch("a2sdlc.adapters.jira_tickets.JIRA"):
            self.adapter = JiraTickets(
                url="https://jira.example.com",
                username="user",
                token="tok",
                github_repo="owner/repo",
            )
        self.mock_jira = self.adapter.jira

    def test_fetch_returns_markdown(self) -> None:
        issue = MagicMock()
        issue.fields.summary = "My Ticket"
        issue.fields.description = "Ticket description here."
        comment1 = MagicMock()
        comment1.author.displayName = "Alice"
        comment1.body = "First comment"
        comment2 = MagicMock()
        comment2.author.displayName = "Bob"
        comment2.body = "Second comment"
        self.mock_jira.issue.return_value = issue  # ty: ignore[invalid-assignment]
        self.mock_jira.comments.return_value = [comment1, comment2]

        result = self.adapter.fetch("PROJ-1")

        assert "My Ticket" in result
        assert "Ticket description here." in result
        assert "First comment" in result
        assert "Second comment" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_get_status(self) -> None:
        issue = MagicMock()
        issue.fields.status.name = "In Progress"
        self.mock_jira.issue.return_value = issue  # ty: ignore[invalid-assignment]

        assert self.adapter.get_status("PROJ-1") == "In Progress"

    def test_create_comment(self) -> None:
        comment = MagicMock()
        comment.id = 12345
        self.mock_jira.add_comment.return_value = comment

        result = self.adapter.create_comment("PROJ-1", "Hello world")

        assert result == "12345"
        self.mock_jira.add_comment.assert_called_once_with("PROJ-1", "Hello world")

    def test_update_comment(self) -> None:
        comment = MagicMock()
        self.mock_jira.comment.return_value = comment

        self.adapter.update_comment("PROJ-1", "999", "Updated body")

        self.mock_jira.comment.assert_called_once_with("PROJ-1", "999")
        comment.update.assert_called_once_with(body="Updated body")

    def test_transition_found(self) -> None:
        self.mock_jira.transitions.return_value = [
            {"id": "10", "name": "To Do"},
            {"id": "20", "name": "In Progress"},
            {"id": "30", "name": "Done"},
        ]

        self.adapter.transition("PROJ-1", "in progress")

        self.mock_jira.transition_issue.assert_called_once_with("PROJ-1", "20")

    def test_transition_not_found_adds_label(self) -> None:
        self.mock_jira.transitions.return_value = [
            {"id": "10", "name": "To Do"},
            {"id": "20", "name": "Done"},
        ]
        issue = MagicMock()
        issue.fields.labels = ["existing-label"]
        self.mock_jira.issue.return_value = issue  # ty: ignore[invalid-assignment]

        self.adapter.transition("PROJ-1", "custom-state")

        self.mock_jira.transition_issue.assert_not_called()
        issue.update.assert_called_once_with(
            fields={"labels": ["existing-label", "custom-state"]}
        )

    @patch("a2sdlc.adapters.jira_tickets.subprocess")
    def test_trigger_next(self, mock_subprocess) -> None:
        payload = {"issue": "PROJ-1", "stage": "plan"}
        self.adapter.trigger_next("a2sdlc-plan", payload)

        mock_subprocess.run.assert_called_once()
        call_args = mock_subprocess.run.call_args
        assert call_args[0][0] == [
            "gh",
            "api",
            "repos/owner/repo/dispatches",
            "-X",
            "POST",
            "--input",
            "-",
        ]
        body = json.loads(call_args[1]["input"])
        assert body["event_type"] == "a2sdlc-plan"
        assert body["client_payload"] == payload
        assert call_args[1]["text"] is True
        assert call_args[1]["check"] is True
