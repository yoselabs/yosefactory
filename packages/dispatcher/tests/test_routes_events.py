from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a2sdlc_dispatcher.hmac_token import mint_token
from a2sdlc_dispatcher.routes_events import build_router
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import ProjectConfig

KEY = b"k" * 32


def _app(jira, settings_mock, runs):
    app = FastAPI()
    app.include_router(build_router(settings=settings_mock, jira=jira, runs=runs))
    return app


def _settings():
    s = MagicMock()
    s.hmac_signing_key.get_secret_value.return_value = "k" * 32
    s.project_by_key.return_value = ProjectConfig(jira_key="A2X", repo="acme/webapp")
    return s


def test_stage_started_routed_to_jira():
    jira = MagicMock()
    settings = _settings()
    runs = RunsTable()
    runs.register(
        run_id="r1", ticket_key="A2X-42", repo="acme/webapp", project_key="A2X"
    )
    client = TestClient(_app(jira, settings, runs))
    token = mint_token("r1", "A2X-42", key=KEY, ttl_seconds=60)
    r = client.post(
        "/runs/r1/events",
        json={"kind": "stage_started", "stage": "implement"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202
    jira.add_comment.assert_called_once()


def test_bad_token_rejected():
    jira = MagicMock()
    settings = _settings()
    runs = RunsTable()
    runs.register(
        run_id="r1", ticket_key="A2X-42", repo="acme/webapp", project_key="A2X"
    )
    client = TestClient(_app(jira, settings, runs))
    r = client.post(
        "/runs/r1/events",
        json={"kind": "stage_started", "stage": "implement"},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_unknown_run_404():
    jira = MagicMock()
    settings = _settings()
    runs = RunsTable()
    client = TestClient(_app(jira, settings, runs))
    token = mint_token("rX", "A2X-42", key=KEY, ttl_seconds=60)
    r = client.post(
        "/runs/rX/events",
        json={"kind": "stage_started", "stage": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
