from unittest.mock import MagicMock
import pytest
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.settings import ProjectConfig


def make_project() -> ProjectConfig:
    return ProjectConfig(jira_key="A2X", repo="acme/webapp")


def test_add_comment_calls_jira():
    raw = MagicMock()
    client = JiraClient(raw)
    client.add_comment("A2X-42", "hello")
    raw.issue_add_comment.assert_called_once_with("A2X-42", "hello")


def test_transition_by_name_looks_up_id():
    raw = MagicMock()
    raw.get_issue_transitions.return_value = [
        {"id": "11", "name": "Ready"},
        {"id": "21", "name": "In Progress"},
    ]
    client = JiraClient(raw)
    client.transition("A2X-42", to_status="In Progress")
    raw.issue_transition.assert_called_once_with("A2X-42", "21")


def test_transition_unknown_status_raises():
    raw = MagicMock()
    raw.get_issue_transitions.return_value = [{"id": "11", "name": "Ready"}]
    client = JiraClient(raw)
    with pytest.raises(ValueError, match="no transition named"):
        client.transition("A2X-42", to_status="Done")


def test_find_blocked_by_issues():
    raw = MagicMock()
    raw.jql.return_value = {
        "issues": [
            {"key": "A2X-43"},
            {"key": "A2X-44"},
        ]
    }
    client = JiraClient(raw)
    keys = client.find_issues_blocked_only_by(
        "A2X-42", project_key="A2X", blocked_status="Blocked"
    )
    assert keys == ["A2X-43", "A2X-44"]
    raw.jql.assert_called_once()
    jql_arg = raw.jql.call_args.args[0]
    # Critical: must use linkedIssues() JQL function, NOT "is blocked by" = KEY
    assert "linkedIssues" in jql_arg
    assert "blocks" in jql_arg
