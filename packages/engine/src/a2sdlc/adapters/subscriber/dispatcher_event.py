"""DispatcherEventSubscriber — POSTs engine progress events to the dispatcher.

Activates only when DISPATCHER_URL is set. Swallows network failures so the
dispatcher being down cannot break the pipeline (MLflow + console still
capture the run).
"""

from __future__ import annotations

import logging
from typing import Any

from a2sdlc.domain.progress import (
    Metrics,
    Milestone,
    ProgressEvent,
    StageEnd,
    StageStart,
    ToolEntry,
)

logger = logging.getLogger(__name__)


class DispatcherEventSubscriber:
    def __init__(
        self,
        *,
        dispatcher_url: str,
        run_id: str,
        run_hmac: str,
        http: Any,
    ) -> None:
        self._url = dispatcher_url.rstrip("/")
        self._run_id = run_id
        self._hmac = run_hmac
        self._http = http

    async def handle(self, event: ProgressEvent) -> None:
        payload = self._translate(event)
        if payload is None:
            return
        try:
            r = self._http.post(
                f"{self._url}/runs/{self._run_id}/events",
                json=payload,
                headers={"Authorization": f"Bearer {self._hmac}"},
                timeout=10.0,
            )
            if hasattr(r, "raise_for_status"):
                r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — intentional: swallow network failures
            logger.warning(
                "dispatcher POST failed (event=%s): %s", payload.get("kind"), e
            )

    def _translate(self, event: ProgressEvent) -> dict | None:
        # CRITICAL: do NOT emit run_started from the engine. The engine runs
        # once per stage in its own CI process — "first stage_started" per
        # run_id is dedupe'd by the dispatcher, which flips Ready → In Progress
        # exactly once. Emitting run_started here would double-transition.
        if isinstance(event, StageStart):
            return {"kind": "stage_started", "stage": event.stage.value}
        if isinstance(event, StageEnd):
            return {
                "kind": "stage_completed",
                "stage": event.stage.value,
                "ok": event.success,
                "summary": event.error,
            }
        if isinstance(event, (Metrics, Milestone, ToolEntry)):
            return None
        return None
