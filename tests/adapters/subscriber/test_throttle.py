"""Throttle utility — admits the first call, rejects within-window subsequent."""

from __future__ import annotations

import time

from a2sdlc.adapters.subscriber._throttle import Throttle


def test_first_call_admitted() -> None:
    t = Throttle(min_interval=1.0)
    assert t.ready() is True


def test_second_call_within_window_rejected() -> None:
    t = Throttle(min_interval=10.0)
    assert t.ready() is True
    assert t.ready() is False


def test_call_after_window_admitted(monkeypatch) -> None:
    fake_now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    t = Throttle(min_interval=1.0)
    assert t.ready() is True
    fake_now[0] = 0.5
    assert t.ready() is False
    fake_now[0] = 1.5
    assert t.ready() is True


def test_zero_interval_always_admits(monkeypatch) -> None:
    fake_now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    t = Throttle(min_interval=0.0)
    assert t.ready() is True
    assert t.ready() is True
    assert t.ready() is True
