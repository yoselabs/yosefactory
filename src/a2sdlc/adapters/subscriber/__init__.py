"""Subscriber Protocol + in-tree subscriber impls.

Subscribers consume ``ProgressEvent`` instances from ``ProgressState``. Concrete
impls filter events by ``isinstance`` and ignore types they don't handle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from a2sdlc.evaluation.progress import ProgressEvent


class Subscriber(Protocol):
    """Receives ``ProgressEvent`` instances from ``ProgressState``.

    Implementations filter by ``isinstance`` and ignore event types they
    don't care about. ``handle`` is async because the runner is already
    async; sync subscribers just don't ``await`` anything inside.
    """

    async def handle(self, event: "ProgressEvent") -> None: ...


from a2sdlc.adapters.subscriber.console import ConsoleSubscriber  # noqa: E402
from a2sdlc.adapters.subscriber.gh_actions import GhActionsLogSubscriber  # noqa: E402
from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber  # noqa: E402
from a2sdlc.adapters.subscriber.mlflow_trace import MlflowTraceSubscriber  # noqa: E402

__all__ = [
    "Subscriber",
    "ConsoleSubscriber",
    "GhActionsLogSubscriber",
    "GhCommentSubscriber",
    "MlflowTraceSubscriber",
]
