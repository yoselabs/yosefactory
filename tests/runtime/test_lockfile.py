"""PID lockfile with signal-handler cleanup. Spec §Failure modes."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from a2sdlc.runtime.lockfile import (
    LockfileBusy,
    _read_lock_metadata,
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


def test_read_lock_metadata_returns_none_pair_for_malformed(tmp_path):
    """Malformed lockfile -> (None, None) so callers don't crash mid-error."""
    lock_path = tmp_path / "run.lock"
    lock_path.write_text("not-a-valid-lock-body")
    assert _read_lock_metadata(lock_path) == (None, None)


def test_read_lock_metadata_returns_none_pair_for_missing(tmp_path):
    assert _read_lock_metadata(tmp_path / "does-not-exist.lock") == (None, None)


# ── Cross-process and signal paths ───────────────────────────────────


def _spawn_child_holding_lock(lock_path: Path, ready_path: Path) -> subprocess.Popen:
    """Start a subprocess that acquires the lock and idles until killed."""
    src = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2] / "packages/engine/src")!r})
        from a2sdlc.runtime.lockfile import acquire_lock
        with acquire_lock(Path({str(lock_path)!r})):
            Path({str(ready_path)!r}).write_text("ready")
            while True:
                time.sleep(0.05)
        """
    )
    return subprocess.Popen([sys.executable, "-c", src])


def _wait_for(path: Path, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise TimeoutError(f"timeout waiting for {path}")


def test_cross_process_busy_raises_lockfile_busy(tmp_path):
    """Second process's acquire_lock() must raise LockfileBusy via flock EWOULDBLOCK."""
    lock_path = tmp_path / "run.lock"
    ready = tmp_path / "ready"
    proc = _spawn_child_holding_lock(lock_path, ready)
    try:
        _wait_for(ready)
        with pytest.raises(LockfileBusy) as ei:
            with acquire_lock(lock_path):
                pass
        assert "another a2sdlc run" in str(ei.value)
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)


def test_signal_handler_releases_lockfile_on_sigterm(tmp_path):
    """Child holding the lock receives SIGTERM; cleanup handler removes the lockfile."""
    lock_path = tmp_path / "run.lock"
    ready = tmp_path / "ready"
    proc = _spawn_child_holding_lock(lock_path, ready)
    try:
        _wait_for(ready)
        assert lock_path.exists()
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=5)
        # Signal handler re-raises via os.kill(getpid(), SIGTERM); negative rc
        # on POSIX means terminated by signal -SIGTERM (-15).
        assert rc == -signal.SIGTERM
        assert not lock_path.exists()
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=5)


def test_flock_non_busy_oserror_propagates(tmp_path, monkeypatch):
    """A non-EWOULDBLOCK OSError from flock is re-raised, not converted to LockfileBusy."""
    import fcntl

    lock_path = tmp_path / "run.lock"

    real_flock = fcntl.flock

    def fake_flock(fd, op):
        if op & fcntl.LOCK_EX:
            raise OSError(errno.EIO, "boom")
        return real_flock(fd, op)

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    with pytest.raises(OSError) as ei:
        with acquire_lock(lock_path):
            pass
    assert ei.value.errno == errno.EIO
    # Outer except in acquire_lock must have closed the fd; lockfile must not
    # remain leaked because acquire never finished. The empty file may still
    # be on disk (created by os.open); that's fine — the contract is just
    # "no leaked fd, no fake busy state".
    from a2sdlc.runtime.lockfile import _locked_paths

    key = str(lock_path.resolve() if lock_path.exists() else lock_path)
    assert key not in _locked_paths


def test_release_swallows_oserror_from_flock_unlock(tmp_path, monkeypatch):
    """_release must not propagate OSError from flock LOCK_UN, os.close, or unlink."""
    import fcntl as _fcntl

    from a2sdlc.runtime import lockfile as lf

    lock_path = tmp_path / "run.lock"

    real_flock = _fcntl.flock

    def flaky_flock(fd, op):
        if op == _fcntl.LOCK_UN:
            raise OSError(errno.EBADF, "already gone")
        return real_flock(fd, op)

    real_close = os.close
    close_calls = {"n": 0}

    def flaky_close(fd):
        # First call inside _release fails; subsequent calls (e.g., from the
        # outer except block) succeed.
        close_calls["n"] += 1
        if close_calls["n"] == 1:
            raise OSError(errno.EBADF, "already closed")
        return real_close(fd)

    def flaky_unlink(self, *a, **kw):
        raise OSError(errno.EACCES, "perm denied")

    # Acquire normally first, then patch _release internals before exit.
    with acquire_lock(lock_path):
        monkeypatch.setattr(_fcntl, "flock", flaky_flock)
        monkeypatch.setattr(lf.os, "close", flaky_close)
        monkeypatch.setattr(Path, "unlink", flaky_unlink)
    # Successful exit means all three OSErrors were swallowed.
