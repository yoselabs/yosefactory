"""Time-window guard. No progress semantics; reusable by any subscriber."""

from __future__ import annotations

import time


class Throttle:
    """Admits the first call, then rejects until ``min_interval`` seconds pass."""

    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._last: float | None = None

    def ready(self) -> bool:
        now = time.monotonic()
        if self._last is None or now - self._last >= self._min:
            self._last = now
            return True
        return False
