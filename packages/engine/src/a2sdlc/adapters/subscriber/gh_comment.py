"""GhCommentSubscriber — throttled status edits + final summary on issue/PR comment."""

from __future__ import annotations

from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import (
    Metrics,
    ProgressEvent,
    ProgressState,
    StageEnd,
    StageStart,
)
from a2sdlc.domain.progress_format import format_progress
from a2sdlc.adapters.subscriber._throttle import Throttle


class GhCommentSubscriber:
    """Edits the GitHub issue/PR comment with progress updates.

    - ``StageStart``: caches the stage so ``format_progress`` can render it.
    - ``Metrics``: throttled to ``throttle_seconds`` (default 5s) — protects
      against GitHub API rate limits. Each emit re-renders ``format_progress``
      which already includes the latest milestones list, so milestone events
      land in the comment via the next throttled tick — no separate handler.
    - ``StageEnd``: never throttled; calls ``comment.finalize`` with a
      definitive summary including cost and turn count.
    """

    def __init__(
        self,
        comment_handle,  # CommentManager-like (has update/finalize)
        progress_state: ProgressState,
        throttle_seconds: float = 5.0,
    ) -> None:
        self._comment = comment_handle
        self._state = progress_state
        self._throttle = Throttle(min_interval=throttle_seconds)
        self._stage: StageName | None = None

    async def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            self._stage = event.stage
        elif isinstance(event, Metrics):
            if self._throttle.ready():
                text = format_progress(
                    self._stage.value if self._stage else "?", self._state
                )
                self._comment.update(text)
        elif isinstance(event, StageEnd):
            icon = "\u2705" if event.success else "\u274c"
            self._comment.finalize(
                f"{icon} {event.stage.value} done — "
                f"${event.final_metrics.total_cost_usd:.2f}, "
                f"{event.final_metrics.num_turns} turns"
            )
