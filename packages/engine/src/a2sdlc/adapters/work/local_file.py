"""Local file-backed WorkAdapter — runtime state lives under `.a2sdlc/state/`.

Stand-in for Jira/GitHub work-item operations when running the engine fully
offline. Ticket body is copied to `.a2sdlc/state/ticket.md`. Handover content
is written per-stage to `.a2sdlc/state/handover/<stage>.md`. Feedback signal
is detected by the presence of an unconsumed `.a2sdlc/state/feedback.json`
(written by the local review adapter). The entire `.a2sdlc/state/` folder is
treated as opaque runtime data and stripped pre-merge.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName

logger = logging.getLogger(__name__)

_TICKET_FILE = "ticket.md"
_PR_FILE = "pr.json"
_FEEDBACK_FILE = "feedback.json"
_HANDOVER_DIR = "handover"


class LocalFileWorkAdapter:
    """File-backed mock of the WorkAdapter protocol."""

    def __init__(
        self,
        project_root: Path,
        session_id: str,
        stage: StageName,
        ticket_path: Path | None,
    ) -> None:
        self._root = project_root
        self._session_id = session_id
        self._stage = stage

        self._a2sdlc_dir = project_root / ".a2sdlc"
        self._a2sdlc_dir.mkdir(exist_ok=True)
        self._state_dir = self._a2sdlc_dir / "state"
        self._state_dir.mkdir(exist_ok=True)
        self._handover_dir = self._state_dir / _HANDOVER_DIR
        self._handover_dir.mkdir(exist_ok=True)

        if ticket_path is not None:
            shutil.copyfile(ticket_path, self._state_dir / _TICKET_FILE)

        self._comment_counter = 0
        self._comment_stage: dict[str, StageName] = {}

    # ── internal helpers ─────────────────────────────────────────────

    @property
    def _ticket_path(self) -> Path:
        return self._state_dir / _TICKET_FILE

    @property
    def _pr_path(self) -> Path:
        return self._state_dir / _PR_FILE

    @property
    def _feedback_path(self) -> Path:
        return self._state_dir / _FEEDBACK_FILE

    def _read_pr_number(self) -> int | None:
        if not self._pr_path.exists():
            return None
        try:
            data = json.loads(self._pr_path.read_text())
        except json.JSONDecodeError:
            return None
        value = data.get("pr_number")
        if isinstance(value, int):
            return value
        return None

    def _is_unconsumed_feedback(self) -> bool:
        if not self._feedback_path.exists():
            return False
        try:
            data = json.loads(self._feedback_path.read_text())
        except json.JSONDecodeError:
            return False
        return data.get("consumed", False) is False

    # ── protocol methods ─────────────────────────────────────────────

    def parse_event(self) -> PipelineEvent:
        pr_number = self._read_pr_number()
        if self._is_unconsumed_feedback():
            return PipelineEvent(
                key=self._session_id,
                trigger_stage=None,
                is_feedback=True,
                pr_number=pr_number,
            )
        return PipelineEvent(
            key=self._session_id,
            trigger_stage=self._stage,
            is_feedback=False,
            pr_number=pr_number,
        )

    def is_ticket_active(self, key: str) -> bool:
        # Local file adapter has no concept of a closed ticket — the caller
        # controls when the loop stops.
        return True

    def get_ticket(self, key: str) -> str:
        if not self._ticket_path.exists():
            return ""
        return self._ticket_path.read_text()

    def get_labels(self, key: str) -> list[str]:
        return []

    def begin_comment(self, key: str) -> str:
        self._comment_counter += 1
        cid = f"{key}-{self._stage.value}-{self._comment_counter}"
        self._comment_stage[cid] = self._stage
        return cid

    def update_progress(self, comment_id: str, body: str) -> None:
        # Live progress flows through subscribers, not WorkAdapter.
        return None

    def finalize_comment(self, comment_id: str, body: str) -> None:
        stage = self._comment_stage.get(comment_id, self._stage)
        target = self._handover_dir / f"{stage.value}.md"
        target.write_text(body)

    def get_current_stage(self, key: str) -> StageName | None:
        # Local adapter has no persistent stage record outside state.json —
        # callers use state.json directly for local runs.
        return None

    def set_current_stage(self, key: str, stage: StageName) -> None:
        logger.info("set_current_stage key=%s stage=%s", key, stage.value)

    def mark_done(self, key: str) -> None:
        logger.info("mark_done key=%s", key)

    def mark_blocked(self, key: str, reason: str) -> None:
        logger.info("mark_blocked key=%s reason=%s", key, reason)

    def mark_needs_input(self, key: str) -> None:
        logger.info("mark_needs_input key=%s", key)

    def format_branch(self, ticket_key: str) -> str:
        return f"a2sdlc/{ticket_key}"

    def collect_issue_feedback(self, key: str, since: datetime) -> list[FeedbackItem]:
        return []

    def find_last_handover(self, key: str) -> HandoverComment | None:
        if not self._handover_dir.exists():
            return None
        candidates = [
            p for p in self._handover_dir.iterdir() if p.is_file() and p.suffix == ".md"
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        try:
            stage = StageName(latest.stem)
        except ValueError:
            return None
        mtime = latest.stat().st_mtime
        return HandoverComment(
            stage=stage,
            run_id=str(mtime),
            body=latest.read_text(),
            created_at=datetime.fromtimestamp(mtime, tz=timezone.utc),
            location="issue",
        )


__all__ = ["LocalFileWorkAdapter"]
