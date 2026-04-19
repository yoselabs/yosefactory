import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from a2sdlc_dispatcher.routes_jira import build_router
from a2sdlc_dispatcher.settings import ProjectConfig
from a2sdlc_dispatcher.runs_table import RunsTable


def _build_app(settings_mock, gh_app_mock, runs):
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(
        build_router(settings=settings_mock, gh_app=gh_app_mock, runs=runs)
    )
    return app


def _event_payload(
    ticket_key: str, to_status: str, description: str = "As a user, I want X."
) -> bytes:
    return json.dumps(
        {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": ticket_key,
                "fields": {"status": {"name": to_status}, "description": description},
            },
            "changelog": {"items": [{"field": "status", "toString": to_status}]},
        }
    ).encode()


def _sign(body: bytes, secret: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def _settings():
    s = MagicMock()
    s.jira_webhook_secret.get_secret_value.return_value = "shh"
    s.hmac_signing_key.get_secret_value.return_value = "k" * 32
    s.project_by_key.return_value = ProjectConfig(jira_key="A2X", repo="acme/webapp")
    s.self_url = "https://dispatcher.yose.tld"
    return s


async def test_ready_transition_triggers_workflow():
    settings = _settings()
    gh = AsyncMock()
    runs = RunsTable()
    app = _build_app(settings, gh, runs)
    client = TestClient(app)

    body = _event_payload("A2X-42", "Ready")
    r = client.post(
        "/jira/events",
        content=body,
        headers={"X-Hub-Signature": _sign(body, b"shh")},
    )
    assert r.status_code == 202
    gh.trigger_workflow_dispatch.assert_awaited_once()
    call = gh.trigger_workflow_dispatch.await_args.kwargs
    assert call["repo"] == "acme/webapp"
    assert call["inputs"]["ticket_key"] == "A2X-42"
    assert call["inputs"]["ticket_body"] == "As a user, I want X."
    assert call["inputs"]["dispatcher_url"] == "https://dispatcher.yose.tld"
    assert "run_id" in call["inputs"]
    assert "run_hmac" in call["inputs"]
    assert runs.active_run_for("A2X-42") is not None


def test_bad_signature_rejected():
    settings = _settings()
    gh = AsyncMock()
    runs = RunsTable()
    app = _build_app(settings, gh, runs)
    client = TestClient(app)
    body = _event_payload("A2X-42", "Ready")
    r = client.post(
        "/jira/events",
        content=body,
        headers={"X-Hub-Signature": "bogus"},
    )
    assert r.status_code == 401


def test_non_ready_status_ignored():
    settings = _settings()
    gh = AsyncMock()
    runs = RunsTable()
    app = _build_app(settings, gh, runs)
    client = TestClient(app)
    body = _event_payload("A2X-42", "In Progress")
    r = client.post(
        "/jira/events",
        content=body,
        headers={"X-Hub-Signature": _sign(body, b"shh")},
    )
    assert r.status_code == 204
    gh.trigger_workflow_dispatch.assert_not_awaited()
