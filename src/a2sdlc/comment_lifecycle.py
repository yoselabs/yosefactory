"""CommentManager — enforces the one-comment-per-stage-run lifecycle."""

from __future__ import annotations

import logging

from a2sdlc.adapters.retry import must_succeed
from a2sdlc.adapters.work import WorkAdapter

logger = logging.getLogger(__name__)


class CommentManager:
    """Manages the lifecycle of a single progress comment per stage run.

    Lifecycle contract:
    - ``start`` once — creates a comment via the adapter.
    - ``update`` many times — overwrites the comment body.
    - ``finalize`` once — writes the final body with retry; idempotent after that.
    - Calling ``start`` again before ``finalize`` raises ``RuntimeError``.
    """

    def __init__(self, work: WorkAdapter, ticket_key: str) -> None:
        self._work = work
        self._ticket_key = ticket_key
        self._comment_id: str | None = None
        self._finalized: bool = False

    # ── public API ────────────────────────────────────────────────────

    @property
    def comment_id(self) -> str | None:
        """Current comment ID, or ``None`` if ``start`` hasn't been called."""
        return self._comment_id

    def start(self, stage_name: str) -> None:
        """Create a new progress comment for *stage_name*.

        Raises ``RuntimeError`` if the previous comment hasn't been finalized.
        """
        if self._comment_id is not None and not self._finalized:
            raise RuntimeError(
                f"Cannot start new comment for stage '{stage_name}': "
                f"comment {self._comment_id!r} has not been finalized yet. "
                "Call finalize() before starting a new stage."
            )
        self._comment_id = self._work.begin_comment(self._ticket_key)
        self._finalized = False
        logger.debug(
            "comment.start stage=%s comment_id=%s key=%s",
            stage_name,
            self._comment_id,
            self._ticket_key,
        )

    def update(self, body: str) -> None:
        """Overwrite the current comment body.

        No-op (with a warning) if ``start`` hasn't been called.
        """
        if self._comment_id is None:
            logger.warning(
                "comment.update called before start — ignoring (key=%s)",
                self._ticket_key,
            )
            return
        self._work.update_progress(self._comment_id, body)

    def finalize(self, body: str) -> None:
        """Write the final comment body with retry.

        Idempotent — subsequent calls after the first are silently ignored.
        """
        if self._finalized:
            return
        must_succeed(self._work.finalize_comment, self._comment_id, body)
        self._finalized = True
        logger.debug(
            "comment.finalize comment_id=%s key=%s",
            self._comment_id,
            self._ticket_key,
        )
