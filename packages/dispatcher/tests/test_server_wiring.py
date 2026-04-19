"""Integration tests for the real FastAPI app created by create_app().

These tests regress a bug where routes_* build_router functions existed
and had their own unit tests, but server.py was never wired to mount
them, making the deployed dispatcher a healthz-only service. Always
exercise the actual app the production entrypoint imports.

Rule: any new router, app-level middleware, or app-level dependency added
to create_app() must be exercised here, not only via route-specific unit
tests that build their own FastAPI(). Route-specific tests cannot catch
wiring gaps, prefix drift, or middleware omissions — this file must.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock


def _env(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "bot@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "fake")
    monkeypatch.setenv("GH_APP_ID", "1")
    monkeypatch.setenv("GH_APP_PRIVATE_KEY", "fake")
    monkeypatch.setenv("GH_APP_INSTALLATION_ID", "1")
    monkeypatch.setenv("HMAC_SIGNING_KEY", "k" * 32)
    monkeypatch.setenv("SELF_URL", "http://localhost:8000")
    monkeypatch.setenv("PROJECTS_JSON", '[{"jira_key":"DEMO","repo":"acme/webapp"}]')
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "shh")
    monkeypatch.setenv("GH_WEBHOOK_SECRET", "shh")


def test_app_registers_all_expected_routes(monkeypatch):
    _env(monkeypatch)
    from a2sdlc_dispatcher.server import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    # Every public endpoint the dispatcher promises must be mounted on the real app,
    # not just reachable via a test-local FastAPI() in route-specific unit tests.
    assert "/healthz" in paths
    assert "/jira/events" in paths
    assert "/gh/events" in paths
    assert "/runs/{run_id}/events" in paths


def test_healthz_via_real_app(monkeypatch):
    _env(monkeypatch)
    from fastapi.testclient import TestClient

    from a2sdlc_dispatcher.server import create_app

    client = TestClient(create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_jira_events_unsigned_rejected_via_real_app(monkeypatch):
    """The real app must enforce signature checks — confirms router is mounted
    with the correct settings dependency."""
    _env(monkeypatch)
    from fastapi.testclient import TestClient

    from a2sdlc_dispatcher.server import create_app

    client = TestClient(create_app())
    r = client.post(
        "/jira/events",
        json={"issue": {"key": "DEMO-1", "fields": {"status": {"name": "Ready"}}}},
    )
    assert r.status_code == 401


def test_jira_events_signed_happy_path_reaches_gh_app(monkeypatch):
    """Signed Ready transition must flow through routes_jira → GHAppClient.

    This is the positive counterpart to the 401 test: a 401 alone proves only
    that *something* rejected the request, not that our router handled it.
    By asserting GHAppClient.trigger_workflow_dispatch is awaited with the
    correct inputs, we prove the router is mounted *and* wired to the
    Settings that loaded PROJECTS_JSON.
    """
    _env(monkeypatch)

    from a2sdlc_dispatcher import gh_app as gh_app_mod
    from a2sdlc_dispatcher.server import create_app

    dispatch_mock = AsyncMock()
    monkeypatch.setattr(
        gh_app_mod.GHAppClient, "trigger_workflow_dispatch", dispatch_mock
    )

    from fastapi.testclient import TestClient

    client = TestClient(create_app())

    body = json.dumps(
        {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": "DEMO-1",
                "fields": {
                    "status": {"name": "Ready"},
                    "description": "As a user, I want auth.",
                },
            },
        }
    ).encode()
    sig = hmac.new(b"shh", body, hashlib.sha256).hexdigest()

    r = client.post("/jira/events", content=body, headers={"X-Hub-Signature": sig})
    assert r.status_code == 202, r.text
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.await_args is not None
    call = dispatch_mock.await_args.kwargs
    assert call["repo"] == "acme/webapp"
    assert call["inputs"]["ticket_key"] == "DEMO-1"
    assert call["inputs"]["ticket_body"] == "As a user, I want auth."
    assert "run_id" in call["inputs"]
    assert "run_hmac" in call["inputs"]
