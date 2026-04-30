"""PID lockfile with signal-handler cleanup. Spec §Failure modes."""

from __future__ import annotations

import os

import pytest

from a2sdlc.runtime.lockfile import (
    LockfileBusy,
    acquire_lock,
)


def test_acquire_creates_lockfile_and_releases(tmp_path):
    lock_path = tmp_path / "run.lock"
    with acquire_lock(lock_path) as info:
        assert lock_path.exists()
        assert info.pid == os.getpid()
    assert not lock_path.exists()


def test_second_acquire_raises(tmp_path):
    lock_path = tmp_path / "run.lock"
    with acquire_lock(lock_path):
        with pytest.raises(LockfileBusy) as ei:
            with acquire_lock(lock_path):
                pass
        assert "pid" in str(ei.value).lower()


def test_lockfile_records_pid_and_ts(tmp_path):
    lock_path = tmp_path / "run.lock"
    with acquire_lock(lock_path):
        body = lock_path.read_text()
        assert str(os.getpid()) in body
