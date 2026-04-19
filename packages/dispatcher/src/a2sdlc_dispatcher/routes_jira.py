"""POST /jira/events — Jira webhook ingestion."""

from __future__ import annotations

from typing import Any

import ulid
from fastapi import APIRouter, HTTPException, Request

from a2sdlc_dispatcher.gh_app import GHAppClient
from a2sdlc_dispatcher.hmac_token import mint_token
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import Settings
from a2sdlc_dispatcher.webhook_sig import SigError, verify_jira_sig


def build_router(
    *, settings: Settings, gh_app: GHAppClient, runs: RunsTable
) -> APIRouter:
    router = APIRouter()

    @router.post("/jira/events")
    async def jira_events(request: Request):
        body = await request.body()
        secret = (
            settings.jira_webhook_secret.get_secret_value().encode()
            if settings.jira_webhook_secret
            else None
        )
        if secret is not None:
            try:
                verify_jira_sig(
                    body=body,
                    header=request.headers.get("X-Hub-Signature"),
                    secret=secret,
                )
            except SigError:
                raise HTTPException(status_code=401, detail="bad signature") from None

        payload: dict[str, Any] = await request.json()
        issue = payload.get("issue") or {}
        ticket_key = issue.get("key")
        fields = issue.get("fields", {}) or {}
        status_name = fields.get("status", {}).get("name")

        # Jira webhook payload carries the issue description in fields.description
        # (may be an ADF object or a plain string depending on Jira config).
        ticket_body_raw = fields.get("description") or ""
        if isinstance(ticket_body_raw, dict):
            ticket_body = _flatten_adf(ticket_body_raw)
        else:
            ticket_body = str(ticket_body_raw)
        # Workflow inputs have a soft ~65535 char cap; truncate conservatively.
        if len(ticket_body) > 60_000:
            ticket_body = ticket_body[:60_000] + "\n\n…(truncated)"

        if not ticket_key or not status_name:
            raise HTTPException(
                status_code=400, detail="missing issue.key or status.name"
            )

        project_key = ticket_key.split("-")[0]
        try:
            project = settings.project_by_key(project_key)
        except KeyError:
            return _no_content()

        if status_name != project.status_ready:
            return _no_content()

        run_id = str(ulid.ULID())
        key_bytes = settings.hmac_signing_key.get_secret_value().encode()
        run_hmac = mint_token(run_id, ticket_key, key=key_bytes, ttl_seconds=86400)

        runs.register(
            run_id=run_id,
            ticket_key=ticket_key,
            repo=project.repo,
            project_key=project_key,
        )

        dispatcher_url = settings.self_url or str(request.base_url).rstrip("/")

        await gh_app.trigger_workflow_dispatch(
            repo=project.repo,
            workflow_filename="a2sdlc-split.yml",
            ref=project.default_base,
            inputs={
                "ticket_key": ticket_key,
                "ticket_body": ticket_body,
                "run_id": run_id,
                "run_hmac": run_hmac,
                "base_branch": project.default_base,
                "dispatcher_url": dispatcher_url,
            },
        )

        from fastapi.responses import Response

        return Response(status_code=202)

    return router


def _no_content():
    from fastapi.responses import Response

    return Response(status_code=204)


def _flatten_adf(node: dict) -> str:
    """Recursively collect ADF text nodes into a single string."""
    out: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "text" and "text" in node:
            out.append(str(node["text"]))
        for child in node.get("content", []) or []:
            out.append(_flatten_adf(child))
        if node.get("type") in {
            "paragraph",
            "heading",
            "bulletList",
            "orderedList",
            "listItem",
        }:
            out.append("\n")
    return "".join(out)
