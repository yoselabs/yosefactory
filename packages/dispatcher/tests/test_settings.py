import json
import pytest
from a2sdlc_dispatcher.settings import Settings


PROJECTS = json.dumps(
    [
        {
            "jira_key": "A2X",
            "repo": "acme/webapp",
            "default_base": "main",
        },
        {
            "jira_key": "BILL",
            "repo": "acme/billing",
            "status_ready": "Backlog → Ready",
        },
    ]
)


def test_loads_required_fields(monkeypatch):
    monkeypatch.setenv("PROJECTS_JSON", PROJECTS)
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "bot@acme.com")
    monkeypatch.setenv("JIRA_TOKEN", "x")
    monkeypatch.setenv("GH_APP_ID", "12345")
    monkeypatch.setenv("GH_APP_PRIVATE_KEY", "dummy-pem")
    monkeypatch.setenv("GH_APP_INSTALLATION_ID", "99")
    monkeypatch.setenv("HMAC_SIGNING_KEY", "k" * 32)

    s = Settings()  # ty: ignore[missing-argument]
    assert len(s.projects) == 2
    assert s.project_by_key("A2X").repo == "acme/webapp"
    assert s.project_by_key("BILL").status_ready == "Backlog → Ready"
    # defaults applied
    assert s.project_by_key("A2X").status_ready == "Ready"


def test_missing_required_raises(monkeypatch):
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    with pytest.raises(Exception):
        Settings()  # ty: ignore[missing-argument]


def test_unknown_project_key(monkeypatch):
    monkeypatch.setenv("PROJECTS_JSON", PROJECTS)
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_USER", "bot@acme.com")
    monkeypatch.setenv("JIRA_TOKEN", "x")
    monkeypatch.setenv("GH_APP_ID", "12345")
    monkeypatch.setenv("GH_APP_PRIVATE_KEY", "dummy-pem")
    monkeypatch.setenv("GH_APP_INSTALLATION_ID", "99")
    monkeypatch.setenv("HMAC_SIGNING_KEY", "k" * 32)

    s = Settings()  # ty: ignore[missing-argument]
    with pytest.raises(KeyError):
        s.project_by_key("UNKNOWN")
