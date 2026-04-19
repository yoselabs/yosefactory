"""FastAPI app entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from atlassian import Jira as AtlassianJira
from fastapi import FastAPI

from a2sdlc_dispatcher.gh_app import GHAppClient
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.routes_events import build_router as build_events_router
from a2sdlc_dispatcher.routes_github import build_router as build_gh_router
from a2sdlc_dispatcher.routes_jira import build_router as build_jira_router
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()  # ty: ignore[missing-argument]  # fields loaded from env
    http = httpx.AsyncClient(timeout=30.0)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await http.aclose()

    app = FastAPI(title="a2sdlc-dispatcher", version="0.1.0", lifespan=lifespan)

    gh_app = GHAppClient(
        http=http,
        app_id=settings.gh_app_id,
        private_key_pem=settings.gh_app_private_key.get_secret_value(),
        installation_id=settings.gh_app_installation_id,
    )
    raw_jira = AtlassianJira(
        url=settings.jira_base_url,
        username=settings.jira_user,
        password=settings.jira_token.get_secret_value(),
    )
    jira = JiraClient(raw_jira)
    runs = RunsTable()

    app.include_router(build_jira_router(settings=settings, gh_app=gh_app, runs=runs))
    app.include_router(build_events_router(settings=settings, jira=jira, runs=runs))
    app.include_router(build_gh_router(settings=settings, jira=jira))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def run() -> None:
    """Run the service via uvicorn — used by the `a2sdlc-dispatcher` script."""
    import uvicorn

    uvicorn.run(
        "a2sdlc_dispatcher.server:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
