"""Exclusive PID lockfile with signal-handler cleanup.

Spec §Failure modes (lockfile row) + §Stale-lockfile policy. v1 never
auto-reclaims a stale lockfile; recovery is manual `rm`.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any, Callable, Iterator, Union

_SignalHandler = Union[Callable[[int, FrameType | None], Any], int, None]


class LockfileBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class LockInfo:
    pid: int
    started: str  # ISO-8601 UTC


# Process-local registry of paths currently locked by this process.
# POSIX advisory locks (flock/lockf) on macOS do not block same-process
# re-acquisition reliably; this lookaside enforces single-owner per path
# within the process while flock still guards cross-process collisions.
_locked_paths: set[str] = set()


def _read_lock_metadata(lock_path: Path) -> tuple[int | None, str | None]:
    try:
        body = lock_path.read_text().strip()
        pid_str, ts = body.split("\t", 1)
        return int(pid_str), ts
    except Exception:  # noqa: BLE001
        return None, None


@contextlib.contextmanager
def acquire_lock(lock_path: Path) -> Iterator[LockInfo]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path.resolve() if lock_path.exists() else lock_path)
    if key in _locked_paths:
        pid, ts = _read_lock_metadata(lock_path)
        raise LockfileBusy(
            f"another a2sdlc run is in progress on this VM "
            f"(pid {pid} started {ts}). only one run at a time is supported."
        )
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                pid, ts = _read_lock_metadata(lock_path)
                raise LockfileBusy(
                    f"another a2sdlc run is in progress on this VM "
                    f"(pid {pid} started {ts}). only one run at a time is supported."
                ) from None
            raise
        _locked_paths.add(key)
        info = LockInfo(
            pid=os.getpid(),
            started=datetime.now(timezone.utc).isoformat(),
        )
        os.ftruncate(fd, 0)
        os.write(fd, f"{info.pid}\t{info.started}".encode("utf-8"))
        os.fsync(fd)

        previous_handlers: dict[int, _SignalHandler] = {}

        def _cleanup_on_signal(signum, frame):  # noqa: ANN001
            _release(fd, lock_path)
            handler = previous_handlers.get(signum, signal.SIG_DFL)
            signal.signal(signum, handler)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, _cleanup_on_signal)

        try:
            yield info
        finally:
            for sig, h in previous_handlers.items():
                signal.signal(sig, h)
            _locked_paths.discard(key)
            _release(fd, lock_path)
    except Exception:
        _locked_paths.discard(key)
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _release(fd: int, lock_path: Path) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass
