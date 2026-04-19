"""Integration tests for the real FastAPI app created by create_app().

These tests regress a bug where routes_* build_router functions existed
and had their own unit tests, but server.py was never wired to mount
them, making the deployed dispatcher a healthz-only service. Always
exercise the actual app the production entrypoint imports.
"""

from __future__ import annotations


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
