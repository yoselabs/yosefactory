"""Drive `runtime.turn.take_turn` without a person at a terminal — three wake conditions and a bound.

`take_turn` is a function: acquire, classify, do one item, record, commit, exit. Nothing before this
module called it more than once from inside a single process. A factory is that function driven by
something that is not a person (S195's own naming), so the gap this module closes is real, not
cosmetic: every turn to date, including every "live" receipt in `tests/runtime/test_turn_integration.py`,
was a single call a human or a test made once and then stopped.

**Why in-process, not `repository_dispatch`.** The original sketch named GitHub Actions'
self-chaining event as the mechanism. Treated here as a deployment target, not this change's
deliverable (Article XVI): a `.github/workflows/*.yml` that has never fired is exactly what S195
found nine of already. `run_loop` is runnable and observable on this machine with `python -m
yosefactory.runtime.loop`, and its own ledger rows are the receipt. A CI adapter — a workflow step
that calls `main()` once and re-dispatches itself on `repository_dispatch` — is a thin wrapper this
module makes possible and does not itself build.

**Wake conditions, in priority order:**

    ready item      an item is `state == "ready"` right now              -- cheapest, checked first
    external event  the queue's own HEAD moved since the last check      -- something landed
    heartbeat       `wake.heartbeat_seconds` elapsed with neither above  -- keeps planning alive

The first turn always fires immediately (`WakeReason.STARTUP`) -- a loop that waited out its own
heartbeat before ever checking the backlog it was just handed would be a slower `take_turn`, not a
faster one.

**Self-chaining.** After a turn's record is written, the loop does not exit -- it re-evaluates the
bound, then waits for the next wake condition and calls `take_turn` again. That re-evaluation, not
any callback or external trigger, *is* the self-chaining this change exists to add.

**The wake reason is durable, not just returned.** `LoopReport.steps` lives in memory and dies with
the process. `_record_wake` writes a `<slug>.wake.json` sidecar next to each turn's own ledger
record and commits it, so *why a turn ran* is readable from `ledger/runs/` alone, by a later reader
who never saw the `LoopReport` -- the same test S194 applies to every other claim this platform
makes about itself: check the subject on disk, not the return value.

**The bound, stated once.** The loop stops the first time either holds: `bound.max_iterations`
turns have run, or (when set) cumulative spend recorded in `ledger/spend.jsonl` since the loop
started reaches `bound.spend_ceiling_usd`. `max_iterations` has no default and is always required --
there is no infinite mode. Money classes of turn (a claimed item, or a planning turn) are the only
ones that can spend anything; `nothing-ready` turns and the wake-wait between them cost $0 by
construction (`take_turn` never starts an executor when nothing is eligible and nothing needs
planning), so a loop that never has work to do never spends waiting for it.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from yosefactory.protocol.turn import TurnRecord
from yosefactory.runtime import spend
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.runs import slug_for
from yosefactory.runtime.turn import DEFAULT_PLANNING_FRAME, Executor, Places, commit, eligible, items, take_turn
from yosefactory.runtime.verify import DEFAULT_TEST_COMMAND


class LoopError(ValueError):
    """A loop may not run as configured."""


class WakeReason(StrEnum):
    """Why this iteration's turn was taken. Recorded per step so a run's own log answers *why now*."""

    STARTUP = "startup"
    READY_ITEM = "ready_item"
    EXTERNAL_EVENT = "external_event"
    HEARTBEAT = "heartbeat"


class StopReason(StrEnum):
    """Why the loop stopped. Always one of these — a loop that stops for neither reason is a bug."""

    MAX_ITERATIONS = "max_iterations"
    SPEND_CEILING = "spend_ceiling"


@dataclass(frozen=True, slots=True)
class LoopBound:
    """The one sentence: stop at N turns, or at $C spent, whichever comes first.

    `max_iterations` is mandatory — a loop capable of spending money between iterations with nobody
    watching must not have a code path that runs forever by omission. `spend_ceiling_usd` is optional
    because a loop with no money-spending turn ever eligible (e.g. `nothing-ready` only) has nothing
    for a spend ceiling to bound; `max_iterations` alone still bounds it.
    """

    max_iterations: int
    spend_ceiling_usd: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.max_iterations, int) or isinstance(self.max_iterations, bool) or self.max_iterations < 1:
            raise LoopError(f"max_iterations must be a positive integer, got {self.max_iterations!r}")
        if self.spend_ceiling_usd is not None and not (self.spend_ceiling_usd > 0):
            raise LoopError(f"spend_ceiling_usd must be a positive number or None, got {self.spend_ceiling_usd!r}")


@dataclass(frozen=True, slots=True)
class WakeConfig:
    """How the loop watches for the last two wake conditions while idle.

    `poll_seconds` is how often the idle wait re-checks the queue for a ready item or a moved HEAD;
    `heartbeat_seconds` is the ceiling on how long the loop will go with neither before firing anyway.
    Git gives no change notification (architecture.md §6), so this is deliberately a poll, matching
    Argo CD's own default posture rather than inventing a push mechanism this repo has no server for.
    """

    heartbeat_seconds: int
    poll_seconds: int = 5

    def __post_init__(self) -> None:
        for name in ("heartbeat_seconds", "poll_seconds"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise LoopError(f"{name} must be a positive integer, got {value!r}")


@dataclass(frozen=True, slots=True)
class LoopStep:
    """One iteration: why it woke, and the record `take_turn` wrote for it."""

    wake: WakeReason
    record: TurnRecord


@dataclass(frozen=True, slots=True)
class LoopReport:
    """What the loop did, end to end. Never partial — the loop always returns one of these, even
    when its very first bound check stops it before any turn runs."""

    steps: tuple[LoopStep, ...]
    stopped: StopReason
    spend_usd: float


def _queue_head(repo: Path) -> str | None:
    """The queue's own HEAD sha, or `None` if it has none yet (an empty repo, or not a repo at all).

    Used only as a change signal for the external-event wake condition — never trusted as identity,
    never compared across repositories. A queue with no commits (a fresh fixture) reports `None`
    consistently, so "no HEAD yet" is not mistaken for "HEAD moved."
    """
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _refuse_if_dirty(workspace: Path) -> None:
    """Refuse to start the loop if `workspace` has uncommitted changes, before any turn runs.

    Found by `add-scheduled-loop`'s `launchd` receipt, not designed ahead of it: a development
    bind mount that makes source edits live is, by construction, the same mechanism that lets a
    running loop and a human editor race on the same files. `take_turn`'s commit path goes through
    `prek`, which stashes the *entire* tree for the duration of any hook run (S184,
    orchestration.md Article XI) -- against a dirty tree that collides with whatever a human has
    open, unstashed, uncommitted. The first time this happened it surfaced three layers down as
    `TurnError: commit refused: Restored working tree changes from .../prek/patches/....patch` --
    correct in that nothing was lost or corrupted, but a confusing way to learn "someone was
    editing this." This check moves the same refusal to the top, before any executor could run,
    with a message that names the actual condition.

    This is defense in depth, not the primary mitigation -- the primary one is architectural
    (design.md D1): the container's default compose configuration never points the loop at the
    same path it bind-mounts as live source. This guard exists for the case where it is pointed
    there anyway, deliberately or by misconfiguration.
    """
    completed = subprocess.run(
        ["git", "status", "--porcelain"],  # noqa: S607
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0 and completed.stdout.strip():
        raise LoopError(
            f"refusing to start: {workspace} has uncommitted changes -- a running loop and a human "
            "editing the same tree race on take_turn's own commit (see runtime.loop._refuse_if_dirty)"
        )


def _await_wake(
    places: Places,
    wake: WakeConfig,
    *,
    last_head: str | None,
    last_heartbeat: datetime,
    now_fn: Callable[[], datetime],
    sleep_fn: Callable[[float], None],
) -> WakeReason:
    """Block until one condition holds, cheapest check first. Spends nothing — no executor runs here."""
    while True:
        present = items(places.queue)
        if any(eligible(item) for item in present):
            return WakeReason.READY_ITEM
        current_head = _queue_head(places.queue)
        if current_head != last_head:
            return WakeReason.EXTERNAL_EVENT
        if (now_fn() - last_heartbeat).total_seconds() >= wake.heartbeat_seconds:
            return WakeReason.HEARTBEAT
        sleep_fn(wake.poll_seconds)


def _record_wake(places: Places, record: TurnRecord, reason: WakeReason) -> Path:
    """Write and commit a durable sidecar naming why this turn ran, keyed to the same slug as its
    ledger record.

    `take_turn` generates its own `run_id` and commits its own record before returning, so this
    cannot be folded into that commit without changing `take_turn`'s contract — deliberately kept
    out of scope (design.md — Non-goals). What it can do, and what S194 demands: a `LoopStep` alone
    lives only in `LoopReport`'s return value, in memory, gone the moment the process exits or the
    caller only logs a summary. Without this file, *why a turn ran* is exactly the kind of fact
    S195 catalogued nine other instances of — declared (the enum exists), unreachable from disk.
    """
    started = datetime.fromisoformat(record.started_at)
    slug = slug_for(record.run_id, started)
    wake_path = places.ledger / f"{slug}.wake.json"
    wake_path.write_text(json.dumps({"run_id": record.run_id, "wake": reason.value}, indent=2) + "\n", encoding="utf-8")
    commit(places.queue, [wake_path], f"turn({record.run_id}): wake={reason.value}", run_id=record.run_id)
    return wake_path


def run_loop(
    places: Places,
    executor: Executor,
    *,
    limits: Guardrails,
    owner: str,
    skill: Path,
    bound: LoopBound,
    wake: WakeConfig,
    planning_frame: Mapping[str, Any] = DEFAULT_PLANNING_FRAME,
    loop: str = "default",
    proposal_dir: Path | None = None,
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND,
    isolated: bool = True,
    spend_log: Path = spend.SPEND_LOG,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep_fn: Callable[[float], None] = time.sleep,
) -> LoopReport:
    """Self-chain `take_turn` until `bound` says stop. Every iteration is one real turn, recorded.

    The loop never holds an item, a lock, or a decision across iterations — each call to `take_turn`
    is a complete, independent transaction exactly as it is when a human runs one by hand. What this
    function adds is only the thing a human was: deciding *when* to call it again, and stopping.

    Refuses before the first turn if `places.workspace` is dirty (`_refuse_if_dirty`) — see that
    function's docstring for why a bind-mounted dev container makes this the default risk rather
    than a rare accident.
    """
    _refuse_if_dirty(places.workspace)
    start_moment = now_fn()
    steps: list[LoopStep] = []
    iteration = 0
    last_head = _queue_head(places.queue)
    last_heartbeat = start_moment

    def spent_so_far() -> float:
        return spend.total_since(start_moment, spend_log)

    while True:
        # Checked before waking: a count already at its cap needs no wait to know that.
        if iteration >= bound.max_iterations:
            return LoopReport(steps=tuple(steps), stopped=StopReason.MAX_ITERATIONS, spend_usd=spent_so_far())

        if iteration == 0:
            wake_reason = WakeReason.STARTUP
        else:
            wake_reason = _await_wake(
                places, wake, last_head=last_head, last_heartbeat=last_heartbeat, now_fn=now_fn, sleep_fn=sleep_fn
            )

        # Checked again after waking, before spending anything: the wait itself can be where the
        # ceiling was crossed (another turn, another process, another loop), and a check made only
        # before the wait would miss spend that landed during it.
        if bound.spend_ceiling_usd is not None:
            spent = spent_so_far()
            if spent >= bound.spend_ceiling_usd:
                return LoopReport(steps=tuple(steps), stopped=StopReason.SPEND_CEILING, spend_usd=spent)

        record = take_turn(
            places,
            executor,
            limits=limits,
            owner=owner,
            skill=skill,
            planning_frame=planning_frame,
            loop=loop,
            proposal_dir=proposal_dir,
            test_command=test_command,
            isolated=isolated,
        )
        _record_wake(places, record, wake_reason)
        steps.append(LoopStep(wake=wake_reason, record=record))
        iteration += 1
        last_head = _queue_head(places.queue)
        last_heartbeat = now_fn()


def main(argv: Sequence[str] | None = None, *, unattended: bool = False) -> int:
    """Run the loop against one local repository, both queue and workspace (`Places.local`).

    Cross-repo, cross-machine and non-default executor configuration are left to a caller that
    imports `run_loop` directly — this is the shape one person on one machine actually reaches for,
    matching `stall.main`'s scope discipline rather than growing a general-purpose launcher.

    `unattended` makes `--spend-ceiling-usd` a required argument instead of an optional one.
    D022 §3 defers a program-wide cost ceiling on the premise a human is present to watch and
    interrupt a run; that premise holds for a person typing this command and does not hold for a
    scheduler invoking it with nobody there. Rather than re-litigate the deferral, this keeps
    interactive use exactly as it was (`unattended=False`, the default `main()` still gets when
    called directly) and adds the requirement only on the path a scheduler actually takes —
    `scheduled_main()`, below.
    """
    import argparse
    import sys

    from yosefactory.executor import claude
    from yosefactory.runtime.isolation import IsolationPolicy

    parser = argparse.ArgumentParser(prog="python -m yosefactory.runtime.loop")
    parser.add_argument("repo", type=Path, nargs="?", default=Path("."))
    parser.add_argument("--owner", default="loop")
    parser.add_argument("--skill", type=Path, default=Path("workflows/turn-skill.md"))
    parser.add_argument("--max-iterations", type=int, required=True)
    parser.add_argument(
        "--spend-ceiling-usd",
        type=float,
        default=None,
        required=unattended,
        help="Required when invoked unattended (a scheduler, never a person) -- D022 defers a "
        "program-wide ceiling on the premise a human is present; that premise fails here.",
    )
    parser.add_argument("--heartbeat-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=5)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    places = Places.local(repo)
    limits = Guardrails(window=10, wall_clock_seconds=45 * 60, turn_ceiling=40, grace_seconds=20, question_deadline_hours=24)
    policy = IsolationPolicy(isolated=True)

    def executor(
        frame: Mapping[str, Any],
        workspace: Path,
        limits: Guardrails,
        *,
        run_id: str,
        runs_dir: Path,
        invocation: Any = None,
    ) -> Any:
        return claude.run(frame, workspace, limits, run_id=run_id, runs_dir=runs_dir, invocation=invocation, policy=policy)

    report = run_loop(
        places,
        executor,
        limits=limits,
        owner=args.owner,
        skill=args.skill,
        bound=LoopBound(max_iterations=args.max_iterations, spend_ceiling_usd=args.spend_ceiling_usd),
        wake=WakeConfig(heartbeat_seconds=args.heartbeat_seconds, poll_seconds=args.poll_seconds),
    )
    sys.stdout.write(
        f"stopped: {report.stopped.value}; iterations: {len(report.steps)}; spend: ${report.spend_usd:.4f}\n"
    )
    for step in report.steps:
        sys.stdout.write(f"  {step.wake.value:16} {step.record.outcome.value:14} {step.record.note}\n")
    return 0


def scheduled_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for a scheduler (`launchd`, `cron`) — never a person.

    Identical to `main()` except `--spend-ceiling-usd` is mandatory: see `main`'s own docstring for
    why the requirement lives on this entrypoint and not on `main` itself. This is the function
    `ops/launchd/dev.yosefactory.loop.plist.template` names, via the `yosefactory-loop-scheduled`
    console script (`pyproject.toml`) — a scheduler invokes a stable installed script, never
    `python -m` re-typed inside a plist.
    """
    return main(argv, unattended=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
