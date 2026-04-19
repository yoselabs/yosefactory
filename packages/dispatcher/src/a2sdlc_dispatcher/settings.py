"""Dispatcher config — env-driven via pydantic-settings.

Projects come from a JSON array in PROJECTS_JSON. Secrets come from env.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectConfig(BaseModel):
    jira_key: str
    repo: str
    default_base: str = "main"
    status_ready: str = "Ready"
    status_in_progress: str = "In Progress"
    status_review: str = "In Review"
    status_done: str = "Done"
    status_blocked: str = "Blocked"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None, extra="ignore", populate_by_name=True
    )

    projects: list[ProjectConfig] = Field(default_factory=list, alias="PROJECTS_JSON")

    jira_base_url: str
    jira_user: str
    jira_token: SecretStr

    gh_app_id: int
    gh_app_private_key: SecretStr
    gh_app_installation_id: int = 0

    hmac_signing_key: SecretStr

    jira_webhook_secret: SecretStr | None = None
    gh_webhook_secret: SecretStr | None = None
    dokploy_deploy_token: SecretStr | None = None

    # Public URL the dispatcher is reachable at; falls back to request.base_url if empty.
    self_url: str = ""

    @field_validator("projects", mode="before")
    @classmethod
    def _load_projects(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    def project_by_key(self, key: str) -> ProjectConfig:
        for p in self.projects:
            if p.jira_key == key:
                return p
        raise KeyError(f"no project with jira_key={key!r}")
