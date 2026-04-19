"""POST /gh/events — GitHub webhook ingestion (PR merged)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.settings import Settings
from a2sdlc_dispatcher.webhook_sig import SigError, verify_github_sig

CLOSES_PATTERN = re.compile(r"[Cc]loses?\s+([A-Z][A-Z0-9]*-\d+)")


def _no_content():
    from fastapi.responses import Response

    return Response(status_code=204)


def build_router(*, settings: Settings, jira: JiraClient) -> APIRouter:
    router = APIRouter()

    @router.post("/gh/events")
    async def gh_events(request: Request):
        body = await request.body()
        secret = (
            settings.gh_webhook_secret.get_secret_value().encode()
            if settings.gh_webhook_secret
            else None
        )
        if secret is not None:
            try:
                verify_github_sig(
                    body=body,
                    header=request.headers.get("X-Hub-Signature-256"),
                    secret=secret,
                )
            except SigError:
                raise HTTPException(status_code=401, detail="bad signature") from None

        event = request.headers.get("X-GitHub-Event")
        if event != "pull_request":
            return _no_content()

        payload = await request.json()
        if payload.get("action") != "closed":
            return _no_content()
        pr = payload.get("pull_request", {})
        if not pr.get("merged"):
            return _no_content()

        pr_body = pr.get("body") or ""
        match = CLOSES_PATTERN.search(pr_body)
        if not match:
            return _no_content()

        ticket_key = match.group(1)
        project_key = ticket_key.split("-")[0]
        project = settings.project_by_key(project_key)

        jira.transition(ticket_key, to_status=project.status_done)

        candidates = jira.find_issues_blocked_only_by(
            ticket_key,
            project_key=project_key,
            blocked_status=project.status_blocked,
        )
        for dep in candidates:
            blockers = jira.get_blockers(dep)
            all_done = all(status == project.status_done for _key, status in blockers)
            if all_done:
                jira.transition(dep, to_status=project.status_ready)

        from fastapi.responses import Response

        return Response(status_code=202)

    return router
