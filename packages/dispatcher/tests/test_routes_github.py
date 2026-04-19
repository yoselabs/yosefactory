import hashlib
import hmac
import json
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a2sdlc_dispatcher.routes_github import build_router
from a2sdlc_dispatcher.settings import ProjectConfig


SECRET = b"shh"


def _settings():
    s = MagicMock()
    s.gh_webhook_secret.get_secret_value.return_value = "shh"
    s.project_by_key.return_value = ProjectConfig(jira_key="A2X", repo="acme/webapp")
    return s


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def _pr_merged_body(pr_body: str, repo: str = "acme/webapp") -> bytes:
    return json.dumps(
        {
            "action": "closed",
            "pull_request": {
                "merged": True,
                "body": pr_body,
                "html_url": f"https://github.com/{repo}/pull/1",
            },
            "repository": {"full_name": repo},
        }
    ).encode()


def _app(jira, settings):
    app = FastAPI()
    app.include_router(build_router(settings=settings, jira=jira))
    return app


def test_pr_merged_transitions_and_unblocks_dependents():
    jira = MagicMock()
    jira.find_issues_blocked_only_by.return_value = ["A2X-43"]
    jira.get_blockers.return_value = [("A2X-42", "Done")]

    settings = _settings()
    client = TestClient(_app(jira, settings))
    body = _pr_merged_body("Closes A2X-42")
    r = client.post(
        "/gh/events",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert r.status_code == 202
    jira.transition.assert_any_call("A2X-42", to_status="Done")
    jira.transition.assert_any_call("A2X-43", to_status="Ready")


def test_dependent_with_remaining_blockers_not_transitioned():
    jira = MagicMock()
    jira.find_issues_blocked_only_by.return_value = ["A2X-43"]
    jira.get_blockers.return_value = [("A2X-42", "Done"), ("A2X-50", "In Progress")]

    settings = _settings()
    client = TestClient(_app(jira, settings))
    body = _pr_merged_body("Closes A2X-42")
    r = client.post(
        "/gh/events",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert r.status_code == 202
    jira.transition.assert_any_call("A2X-42", to_status="Done")
    ready_calls = [c for c in jira.transition.call_args_list if "Ready" in str(c)]
    assert ready_calls == []


def test_pr_without_closes_is_ignored():
    jira = MagicMock()
    settings = _settings()
    client = TestClient(_app(jira, settings))
    body = _pr_merged_body("Some PR body with no closes directive")
    r = client.post(
        "/gh/events",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert r.status_code == 204
    jira.transition.assert_not_called()
