"""LocalReviewAdapter — writes review markdown into branch state.

Spec §Adapter ecosystem / Local ecosystem.

`post_review` and `post_inline_comments` write to
`.a2sdlc/state/<branch>/reviews/<ts>-cycle-<n>(.md|-inline.md)`.
PR-lifecycle methods are safe no-ops since no PR exists in local mode.
Distinct from `LocalNoopReviewAdapter` (a true no-op for tests) — this
is the user-facing adapter for `a2sdlc run` local mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.stage_outcome import InlineComment


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LocalReviewAdapter:
    """File-backed ReviewAdapter for local-mode runs.

    Writes review markdown under the branch state root. Implementations
    of PR-lifecycle methods (create/update/merge) are no-ops because
    local mode has no PR. The pairing of `post_review` (verdict file)
    and `post_inline_comments` (inline file) lets users browse review
    output as plain markdown.
    """

    state_root: Path
    cycle: int = 1
    clock: Callable[[], datetime] = field(default=_default_clock)

    def _reviews_dir(self) -> Path:
        d = self.state_root / "reviews"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ts_str(self) -> str:
        return self.clock().strftime("%Y-%m-%dT%H-%M-%S")

    # ── ReviewAdapter Protocol ────────────────────────────────────

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int:
        return 0

    def update_pr(self, pr_number: int, title: str, body: str, ticket_key: str) -> None:
        return None

    def update_pr_title(self, pr_number: int, title: str) -> None:
        return None

    def mark_pr_ready(self, pr_number: int) -> None:
        return None

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        return None

    def get_approvals(self, pr_number: int) -> list[Approval]:
        return []

    def post_review(self, pr_number: int, body: str, verdict: str) -> Path:
        path = self._reviews_dir() / f"{self._ts_str()}-cycle-{self.cycle}.md"
        path.write_text(f"verdict: {verdict}\n\n{body}\n")
        return path

    def post_inline_comments(
        self, pr_number: int, comments: list[InlineComment]
    ) -> None:
        if not comments:
            return None
        path = self._reviews_dir() / f"{self._ts_str()}-cycle-{self.cycle}-inline.md"
        blocks: list[str] = []
        for c in comments:
            body_indented = "\n".join(
                "  " + ln for ln in f"agent: {c.body}".splitlines()
            )
            blocks.append(f"{c.file}:{c.line_start}\n{body_indented}")
        path.write_text("\n\n".join(blocks) + "\n")

    def read_pr_diff(self, pr_number: int) -> str:
        return ""

    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]:
        return []

    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]:
        return []

    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        return None


__all__ = ["LocalReviewAdapter"]
