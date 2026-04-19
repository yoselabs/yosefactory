"""POST /runs/{run_id}/events — ingest domain events from running engine."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from a2sdlc_dispatcher.domain_events import DomainEventAdapter
from a2sdlc_dispatcher.event_translator import translate_event_to_jira
from a2sdlc_dispatcher.hmac_token import TokenError, verify_token
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.runs_table import RunNotFound, RunsTable
from a2sdlc_dispatcher.settings import Settings


def build_router(*, settings: Settings, jira: JiraClient, runs: RunsTable) -> APIRouter:
    router = APIRouter()

    @router.post("/runs/{run_id}/events", status_code=202)
    async def ingest(
        run_id: str, request: Request, authorization: str | None = Header(None)
    ):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()

        key = settings.hmac_signing_key.get_secret_value().encode()
        try:
            claims = verify_token(token, key=key)
        except TokenError as e:
            raise HTTPException(status_code=401, detail=str(e)) from None

        if claims.run_id != run_id:
            raise HTTPException(status_code=401, detail="token/run mismatch")

        try:
            entry = runs.get(run_id)
        except RunNotFound:
            raise HTTPException(status_code=404, detail="run not found") from None

        payload = await request.json()
        event = DomainEventAdapter.validate_python(payload)
        project = settings.project_by_key(entry.project_key)
        translate_event_to_jira(
            jira,
            project=project,
            ticket_key=entry.ticket_key,
            run_id=run_id,
            runs=runs,
            event=event,
        )
        return {"ok": True}

    return router
