"""Tests for a2sdlc.adapters.github_tickets — GitHubTickets adapter."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from a2sdlc.adapters.github_tickets import GitHubTickets


@pytest.mark.unit
class TestGitHubTickets:
    def setup_method(self) -> None:
        self.adapter = GitHubTickets(repo="owner/repo")

    @patch("a2sdlc.adapters.github_tickets.gh")
    def test_fetch_returns_markdown(self, mock_gh) -> None:
        mock_gh.return_value = json.dumps(
            {
                "title": "My Issue",
                "body": "Issue description here.",
                "comments": [
                    {"author": {"login": "alice"}, "body": "First comment"},
                    {"author": {"login": "bob"}, "body": "Second comment"},
                ],
                "labels": [{"name": "bug"}],
            }
        )
        result = self.adapter.fetch("42")
        assert "My Issue" in result
        assert "Issue description here." in result
        assert "First comment" in result
        assert "Second comment" in result
        assert "alice" in result
        assert "bob" in result

    @patch("a2sdlc.adapters.github_tickets.gh")
    def test_get_status_with_label(self, mock_gh) -> None:
        mock_gh.return_value = json.dumps(
            {"labels": [{"name": "bug"}, {"name": "prd-complete"}]}
        )
        assert self.adapter.get_status("42") == "prd-complete"

    @patch("a2sdlc.adapters.github_tickets.gh")
    def test_get_status_no_status_label(self, mock_gh) -> None:
        mock_gh.return_value = json.dumps(
            {"labels": [{"name": "bug"}, {"name": "enhancement"}]}
        )
        assert self.adapter.get_status("42") == "open"

    @patch("a2sdlc.adapters.github_tickets.gh")
    def test_create_comment(self, mock_gh) -> None:
        mock_gh.return_value = (
            "https://github.com/owner/repo/issues/42#issuecomment-123456789"
        )
        comment_id = self.adapter.create_comment("42", "Hello world")
        assert comment_id == "123456789"

    @patch("a2sdlc.adapters.github_tickets.gh")
    def test_transition_adds_label(self, mock_gh) -> None:
        self.adapter.transition("42", "prd-complete")
        mock_gh.assert_called_once_with(
            [
                "issue",
                "edit",
                "42",
                "--repo",
                "owner/repo",
                "--add-label",
                "prd-complete",
            ]
        )

    @patch("a2sdlc.adapters.github_tickets.gh")
    def test_trigger_next_sends_json(self, mock_gh) -> None:
        payload = {"issue": "42", "stage": "plan"}
        self.adapter.trigger_next("a2sdlc-plan", payload)
        mock_gh.assert_called_once()
        call_args = mock_gh.call_args
        assert call_args[0][0] == [
            "api",
            "repos/owner/repo/dispatches",
            "-X",
            "POST",
            "--input",
            "-",
        ]
        body = json.loads(call_args[1]["input_text"])
        assert body["event_type"] == "a2sdlc-plan"
        assert body["client_payload"] == payload
