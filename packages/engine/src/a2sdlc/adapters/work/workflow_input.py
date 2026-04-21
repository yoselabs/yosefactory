"""WorkflowInputReader — WorkAdapter impl for Mode 1 (dispatcher-driven).

Reads ticket context from env vars that the dispatcher set via workflow_dispatch
inputs. Does not call Jira. Engine remains ticket-system-agnostic.

Writes (comments, transitions) are NOT performed here — those go over HTTP
via DispatcherEventSubscriber. The write methods below are NO-OPS returning
sentinel values, not NotImplementedError, because CommentManager invokes them
in the engine's normal path and we must not crash Mode 1 runs.
"""

from __future__ import annotations

import os
from datetime import datetime

from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent

_SENTINEL_COMMENT_ID = "dispatcher-routed"


class WorkflowInputReader:
    def parse_event(self) -> PipelineEvent:
        key = os.environ.get("TICKET_KEY")
        stage_str = os.environ.get("A2SDLC_TRIGGER_STAGE", "spec")
        if not key:
            raise SkipEvent("TICKET_KEY not set — not in dispatcher-triggered run")
        try:
            stage = StageName(stage_str.lower())
        except ValueError:
            raise SkipEvent(f"unknown trigger stage {stage_str!r}") from None
        return PipelineEvent(key=key, trigger_stage=stage)

    def is_ticket_active(self, key: str) -> bool:
        # In dispatcher (Mode 1) the dispatcher upstream-filters terminal
        # tickets before triggering the engine. Trust that contract.
        return True

    def get_ticket(self, key: str) -> str:
        body = os.environ.get("TICKET_BODY")
        if body is None:
            raise RuntimeError(
                "TICKET_BODY env var not set — dispatcher must populate it"
            )
        return body

    def get_labels(self, key: str) -> list[str]:
        return []

    # ── no-op writes — tracker-bound side effects flow through DispatcherEventSubscriber ──

    def begin_comment(self, key: str) -> str:
        return _SENTINEL_COMMENT_ID

    def update_progress(self, *args, **kwargs) -> None:
        return None

    def finalize_comment(self, *args, **kwargs) -> None:
        return None

    def get_current_stage(self, key: str) -> StageName | None:
        # Dispatcher-routed mode: stage comes in as the trigger, not read
        # back from the tracker. Return None to force callers to state.json.
        return None

    def set_current_stage(self, *args, **kwargs) -> None:
        return None

    def mark_done(self, *args, **kwargs) -> None:
        return None

    def mark_blocked(self, *args, **kwargs) -> None:
        return None

    def format_branch(self, ticket_key: str) -> str:
        return f"agent/{ticket_key}"

    def collect_issue_feedback(self, key: str, since: datetime) -> list[FeedbackItem]:
        return []

    def find_last_handover(self, key: str) -> HandoverComment | None:
        return None
