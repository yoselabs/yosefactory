"""Bounds a run in wall-clock time and in turns, keeps two runs off one tree, and guarantees a record.

Nine executor surfaces were assessed and not one enforces a cost cap or a wall clock. If the harness
does not bound a run, nothing does.

The load-bearing part is not the killing, it is the record. Termination is a kill, and a killed
process writes nothing — so the supervisor writes on its behalf, marks `enforced_by: harness` so a
harness stop is distinguishable from an honest failure, and computes `dirty` itself after the
process is gone so a torn tree cannot read as a clean one on the next turn.

Invoked, never resident. Nothing here stays up between runs.
"""

from __future__ import annotations

import fcntl
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from yosefactory.protocol.turn import EnforcedBy, Outcome, TurnRecord
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.runs import append, open_run


class SupervisorError(RuntimeError):
    """The run may not start, or could not be governed."""


class LockBusy(RuntimeError):
    """Another run holds the tree. Exit; do not queue — waiting is what creates a resident process."""


@dataclass(frozen=True, slots=True)
class Stop:
    """Why a run ended, from the supervisor's side of the process boundary."""

    reason: str
    by_harness: bool


@contextmanager
def single_flight(lock_path: Path) -> Iterator[None]:
    """Non-blocking exclusive lock. A run that cannot take it exits without work."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockBusy(f"another run holds {lock_path.name}") from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def tree_is_dirty(repo: Path, *, ignore: Path | None = None) -> bool:
    """Computed by the supervisor after the process is gone. Never taken from the agent.

    The stream is excluded because the supervisor writes into it: a marker written at run start is an
    untracked file in the tree the supervisor is about to judge, so an unfiltered read reports every
    run dirty and the field stops distinguishing anything. `dirty` means *the agent* left work
    half-done, never that the harness left its own evidence behind.
    """
    git = shutil.which("git")
    if git is None:
        raise SupervisorError("git is not on PATH; the supervisor cannot determine tree state")
    completed = subprocess.run([git, "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=False)  # noqa: S603
    excluded = None
    if ignore is not None:
        try:
            excluded = ignore.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            excluded = None
    for line in completed.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if not path:
            continue
        if excluded is not None and (path == excluded or path.startswith(f"{excluded}/")):
            continue
        return True
    return False


def _terminate(process: subprocess.Popen[bytes], grace_seconds: int) -> None:
    """SIGTERM, then a grace window in which the agent may still flush its own verdict, then SIGKILL."""
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def govern(
    argv: list[str],
    *,
    repo: Path,
    runs_dir: Path,
    run_id: str,
    guard: Guardrails,
    turn_ceiling: int | None,
    isolated: bool = True,
    turns_taken: Callable[[], int] | None = None,
    verdict: Callable[[], Outcome | None] | None = None,
    poll_seconds: float = 0.05,
    stdout: Path | None = None,
) -> TurnRecord:
    """Run one agent process under a wall clock and a turn ceiling, and leave a record either way.

    `turns_taken` and `verdict` are the seams the executor wires in. Feeding them requires the
    child's stdout, since the verdict is a structured event the agent prints rather than a status it
    returns — hence `stdout`, which names a file the caller may read while the run is still going.
    Left unset the child inherits this process's stdout, so a caller that does not parse is unaffected.

    Redirecting in a shell would be the other way to get the stream, and it is not available: the
    signal would reach the shell rather than the agent, and the grace window exists precisely so the
    agent can flush its own verdict before it dies.
    """
    if turn_ceiling is None:
        raise SupervisorError("a run with no configured turn ceiling does not start; there is no default in any executor")

    started = datetime.now(UTC)
    slug = open_run(runs_dir, run_id, started)
    if stdout is None:
        process = subprocess.Popen(argv, cwd=repo)  # noqa: S603
    else:
        stdout.parent.mkdir(parents=True, exist_ok=True)
        with stdout.open("wb") as sink:
            process = subprocess.Popen(argv, cwd=repo, stdout=sink)  # noqa: S603
    deadline = time.monotonic() + guard.wall_clock_seconds
    stop = Stop(reason="completed", by_harness=False)

    while process.poll() is None:
        if time.monotonic() >= deadline:
            stop = Stop(reason=f"wall clock exceeded ({guard.wall_clock_seconds}s)", by_harness=True)
            _terminate(process, guard.grace_seconds)
            break
        if turns_taken is not None and turns_taken() > turn_ceiling:
            stop = Stop(reason=f"turn ceiling exceeded ({turn_ceiling})", by_harness=True)
            _terminate(process, guard.grace_seconds)
            break
        time.sleep(poll_seconds)

    flushed = verdict() if verdict is not None else None
    if flushed is not None:
        outcome, enforced_by = flushed, EnforcedBy.AGENT
    else:
        # No terminal verdict is failure, even on exit 0: executors print in-run failures as ordinary
        # output. The exit code is evidence, never the verdict.
        outcome, enforced_by = Outcome.FAILED, EnforcedBy.HARNESS

    record = TurnRecord(
        run_id=run_id,
        started_at=started.isoformat(),
        ended_at=datetime.now(UTC).isoformat(),
        outcome=outcome,
        enforced_by=enforced_by,
        dirty=tree_is_dirty(repo, ignore=runs_dir),
        isolated=isolated,
        note=f"{stop.reason}; exit={process.returncode}",
    )
    append(runs_dir, slug, record)
    return record
