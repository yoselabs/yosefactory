"""Tests for GitHubWorkAdapter.parse_event — label, comment, and review routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.adapters.work.github import GitHubWorkAdapter
from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.models import StageName


# ── Helpers ──────────────────────────────────────────────────────────


def _make_work_adapter(trigger_mention: str = "@a2sdlc") -> GitHubWorkAdapter:
    """Create a GitHubWorkAdapter with a mock repo."""
    return GitHubWorkAdapter(repo=MagicMock(), trigger_mention=trigger_mention)


# ── parse_event: label events ──────────────────────────────────────


@pytest.mark.unit
class TestParseEventLabels:
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
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.trigger_stage == StageName.SPEC
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
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.trigger_stage == StageName.IMPLEMENT
        assert result.key == "15"

    def test_proceed_label_triggers_proceed(self, tmp_path: Path) -> None:
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
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.trigger_stage is None
        assert result.is_feedback is False

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
            adapter = _make_work_adapter()
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
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.trigger_stage == StageName.SPEC

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
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.trigger_stage == StageName.REVIEW
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
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_repo.get_pulls.return_value = [mock_pr]
        adapter._repo = mock_repo

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            result = adapter.parse_event()

        assert result.trigger_stage == StageName.REVIEW
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
        adapter = _make_work_adapter()
        mock_repo = MagicMock()
        mock_repo.get_pulls.return_value = []
        adapter._repo = mock_repo

        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            with pytest.raises(SkipEvent, match="no PR found"):
                adapter.parse_event()

    def test_issues_closed_raises_skip(self, tmp_path: Path) -> None:
        """Delayed bot-triggered label events on a closed issue should skip."""
        path = self._write_event(
            tmp_path,
            {
                "action": "labeled",
                "label": {"name": "stage:review"},
                "issue": {"number": 15, "state": "closed", "labels": []},
                "sender": {"type": "Bot"},
            },
        )
        adapter = _make_work_adapter()
        with patch.dict(
            os.environ, {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issues"}
        ):
            with pytest.raises(SkipEvent, match="closed"):
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
            adapter = _make_work_adapter()
            with pytest.raises(SkipEvent, match="action"):
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
            adapter = _make_work_adapter()
            with pytest.raises(SkipEvent):
                adapter.parse_event()


# ── parse_event: comment and review events ──────────────────────────


@pytest.mark.unit
class TestParseEventComments:
    def _write_event(self, tmp_path: Path, event: dict) -> str:
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event))
        return str(event_file)

    def test_issue_comment_with_mention(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "issue": {"number": 15, "labels": [{"name": "agent"}]},
                "sender": {"type": "User"},
                "comment": {"body": "Hey @a2sdlc please re-run this"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issue_comment"},
        ):
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.key == "15"
        assert result.trigger_stage is None
        assert result.is_feedback is True

    def test_issue_comment_without_mention_skips(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "issue": {"number": 15, "labels": [{"name": "agent"}]},
                "sender": {"type": "User"},
                "comment": {"body": "Just a comment without mention"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issue_comment"},
        ):
            adapter = _make_work_adapter()
            with pytest.raises(SkipEvent, match="does not contain @a2sdlc"):
                adapter.parse_event()

    def test_issue_comment_from_bot_skips(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "issue": {"number": 15, "labels": []},
                "sender": {"type": "Bot"},
                "comment": {"body": "@a2sdlc do something"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issue_comment"},
        ):
            adapter = _make_work_adapter()
            with pytest.raises(SkipEvent, match="bot"):
                adapter.parse_event()

    def test_issue_comment_custom_mention(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "issue": {"number": 15, "labels": []},
                "sender": {"type": "User"},
                "comment": {"body": "Hey @mybot please help"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "issue_comment"},
        ):
            adapter = _make_work_adapter(trigger_mention="@mybot")
            result = adapter.parse_event()
        assert result.key == "15"
        assert result.is_feedback is True

    def test_pr_review_submitted(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "submitted",
                "review": {"body": "Looks good", "state": "approved"},
                "pull_request": {"number": 42},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "pull_request_review"},
        ):
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.key == "42"
        assert result.trigger_stage is None
        assert result.is_feedback is True
        assert result.pr_number == 42

    def test_pr_review_from_bot_skips(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "submitted",
                "review": {"body": "Auto review", "state": "approved"},
                "pull_request": {"number": 42},
                "sender": {"type": "Bot"},
            },
        )
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_PATH": path, "GITHUB_EVENT_NAME": "pull_request_review"},
        ):
            adapter = _make_work_adapter()
            with pytest.raises(SkipEvent, match="bot PR review sender"):
                adapter.parse_event()

    def test_pr_review_comment_with_mention(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "comment": {"body": "@a2sdlc fix this line please"},
                "pull_request": {"number": 42},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ,
            {
                "GITHUB_EVENT_PATH": path,
                "GITHUB_EVENT_NAME": "pull_request_review_comment",
            },
        ):
            adapter = _make_work_adapter()
            result = adapter.parse_event()
        assert result.key == "42"
        assert result.trigger_stage is None
        assert result.is_feedback is True
        assert result.pr_number == 42

    def test_pr_review_comment_without_mention_skips(self, tmp_path: Path) -> None:
        path = self._write_event(
            tmp_path,
            {
                "action": "created",
                "comment": {"body": "This needs work"},
                "pull_request": {"number": 42},
                "sender": {"type": "User"},
            },
        )
        with patch.dict(
            os.environ,
            {
                "GITHUB_EVENT_PATH": path,
                "GITHUB_EVENT_NAME": "pull_request_review_comment",
            },
        ):
            adapter = _make_work_adapter()
            with pytest.raises(SkipEvent, match="does not contain @a2sdlc"):
                adapter.parse_event()
