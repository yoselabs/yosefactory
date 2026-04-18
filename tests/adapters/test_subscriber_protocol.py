"""Subscriber Protocol — anything with async handle(event) satisfies it."""

from __future__ import annotations

import pytest

from a2sdlc.adapters.protocols import Subscriber
from a2sdlc.evaluation.progress import GroupClose, ProgressEvent


class _OkSubscriber:
    def __init__(self) -> None:
        self.events: list = []

    async def handle(self, event) -> None:
        self.events.append(event)


def test_class_with_async_handle_is_a_subscriber() -> None:
    s: Subscriber = _OkSubscriber()  # type: ignore[assignment]
    assert hasattr(s, "handle")


@pytest.mark.asyncio
async def test_handle_receives_progress_events() -> None:
    s = _OkSubscriber()
    evt: ProgressEvent = GroupClose()
    await s.handle(evt)
    assert s.events == [evt]
