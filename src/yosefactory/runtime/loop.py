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

**The bound, stated once.** The loop stops the first time `bound.max_iterations` turns have run.
`max_iterations` has no default and is always required -- there is no infinite mode. Money classes
of turn (a claimed item, or a planning turn) are the only ones that can spend anything;
`nothing-ready` turns and the wake-wait between them cost $0 by construction (`take_turn` never
starts an executor when nothing is eligible and nothing needs planning), so a loop that never has
work to do never spends waiting for it.

**No cumulative spend ceiling.** A prior revision of this module also stopped the loop when
cumulative spend recorded in `ledger/spend.jsonl` since the loop started reached a configured
ceiling. Deleted, not repaired (K D034): every unattended invocation runs `--max-iterations 1`, so
the ceiling's own window -- spend recorded since *this process* started -- was always empty at the
one moment the check ran, before the turn that would have filled it. It never once bound anything
in production, and D034 rules out the cross-run cumulative view it was reaching for: per-issue and
per-run spend, read from `ledger/spend.jsonl` directly, is enough. The only remaining spend
enforcement is `Guardrails.cost_ceiling_usd` (`--cost-ceiling-usd`), a single turn's own post-hoc
budget -- unchanged by this deletion.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from yosefactory.board.adapter import BoardAdapter
from yosefactory.board.inbox import ingest
from yosefactory.board.projection import project_all
from yosefactory.protocol.turn import TurnRecord
from yosefactory.runtime import spend, stall
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.runs import ensure_transcripts_ignored, slug_for
from yosefactory.runtime.turn import (
    DEFAULT_PLANNING_FRAME,
    LOCK,
    RUNS,
    Executor,
    Places,
    commit,
    eligible,
    items,
    spend_log_for,
    take_turn,
)
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


@dataclass(frozen=True, slots=True)
class LoopBound:
    """The one sentence: stop at N turns.

    `max_iterations` is mandatory — a loop capable of spending money between iterations with nobody
    watching must not have a code path that runs forever by omission. A prior revision also carried
    an optional cumulative `spend_ceiling_usd`; deleted per K D034, not modified — see this module's
    own docstring for why the check never fired and why the design it reached for is now explicitly
    unwanted.
    """

    max_iterations: int

    def __post_init__(self) -> None:
        if not isinstance(self.max_iterations, int) or isinstance(self.max_iterations, bool) or self.max_iterations < 1:
            raise LoopError(f"max_iterations must be a positive integer, got {self.max_iterations!r}")


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
class BoardConfig:
    """Wires a `BoardAdapter` into the loop, at its own cadence -- decoupled from
    `WakeConfig.poll_seconds` so a board read (a metered network call, `gh api`) never shares a
    frequency with the queue's own cheap local poll (a `glob()` and a `git rev-parse`).

    **Why ingesting a board command can never itself start an executor** (the dispatch's own
    naming of this as the defect to design against, after [[S987]]): `ingest()` is a pure git
    write -- it calls `runtime.turn.append()`/`commit()`, never `take_turn`, never an `Executor`.
    A command's effect on *which turn runs next* is mediated only by the existing `EXTERNAL_EVENT`
    wake condition observing the queue's own `HEAD` -- the same mechanism that already wakes the
    loop for a human's manual push or another process's commit. There is no direct call site from
    "the board poll found something" to "run a turn" for a future change to trip over.

    `actor` is the git actor board-originated commits are recorded under, distinct from the
    loop's own `owner` -- so a later reader of `git log` can tell "Denis typed this on his phone"
    from "the loop decided this," even though both end up as ordinary commits in the same queue.

    `allowed_actors` is required, with no default, because it is threaded straight through to
    `ingest()`'s own required `allowed_actors` (board/inbox.py: workspaces are public, so an
    ungated intake turns a stranger's issue into a work item). Resolving *where* the allowlist
    comes from -- a config file, a flag -- is this constructor's caller's job, not this
    dataclass's or `ingest()`'s: `BoardAdapter` exists precisely to keep forge-specific lookups
    (a default branch, a `.factory/config.json`) out of this interface.
    """

    adapter: BoardAdapter
    allowed_actors: frozenset[str]
    actor: str = "board"
    poll_seconds: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.poll_seconds, int) or isinstance(self.poll_seconds, bool) or self.poll_seconds < 1:
            raise LoopError(f"poll_seconds must be a positive integer, got {self.poll_seconds!r}")


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
    on_tick: Callable[[], None] | None = None,
) -> WakeReason:
    """Block until one condition holds, cheapest check first. Spends nothing — no executor runs here.

    `on_tick`, when given, runs once per pass through this loop, before the wake checks -- this is
    where board polling attaches (`run_loop`'s `_poll_board_if_due`), so a command it applies can
    move `HEAD` and be picked up by the very same pass's `EXTERNAL_EVENT` check. `on_tick` itself
    never returns a wake reason and is never the thing that decides to wake; it only writes to git,
    same as any other external actor this loop already tolerates.
    """
    while True:
        if on_tick is not None:
            on_tick()
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
    spend_log: Path | None = None,
    board: BoardConfig | None = None,
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

    Asserts the transcript-ignore guard (`runs.ensure_transcripts_ignored`) before that dirty
    check, not after (S238): `take_turn` also asserts it, but only after `_refuse_if_dirty` has
    already run once at the top of this function, so a `Places.local` workspace already carrying
    untracked transcripts from a turn that ran before the guard existed would refuse to start
    before `take_turn` ever got the chance to fix it. Calling it here first closes that gap; the
    call inside `take_turn` stays for callers that invoke it directly, without this loop.

    `spend_log` defaults to `None`, meaning "wherever `take_turn` itself just committed this loop's
    rows" (`turn.spend_log_for(places)`) — the same file `_finish` stages into `places.queue`, not
    `runtime.spend.SPEND_LOG`'s package-relative default (`commit-the-spend-row-inside-the-turn`:
    those two are the same path only under `Places.local`, and this loop is exactly the caller for
    which they can differ). A caller pointing this loop at a real `Places` with a real queue never
    needs to pass it; a test pointing both `take_turn` and this ceiling check at the same isolated
    fixture still may, and both must agree — see `tests/runtime/test_loop.py`'s `spend_log` fixture.

    When `board` is given, two things happen that are otherwise only reachable by calling
    `board.inbox.ingest()` / `board.projection.project_all()` by hand (`turn-loop/board-wiring`):
    unconsumed board commands are applied at `board.poll_seconds`, independent of `wake`'s own
    cadence, and every turn's result — including the pre-existing queue state before the loop's
    first turn — is projected back to the board. Neither ever starts an executor; see
    `BoardConfig`'s own docstring for why that is structural, not a convention.
    """
    ensure_transcripts_ignored(places.ledger, places.workspace)
    _refuse_if_dirty(places.workspace)
    resolved_spend_log = spend_log if spend_log is not None else spend_log_for(places)
    start_moment = now_fn()
    steps: list[LoopStep] = []
    iteration = 0
    last_head = _queue_head(places.queue)
    last_heartbeat = start_moment
    last_board_poll: datetime | None = None

    def poll_board_if_due() -> None:
        nonlocal last_board_poll
        if board is None:
            return
        now = now_fn()
        if last_board_poll is not None and (now - last_board_poll).total_seconds() < board.poll_seconds:
            return
        ingest(places.queue, board.adapter, actor=board.actor, allowed_actors=board.allowed_actors)
        last_board_poll = now

    def project_to_board() -> None:
        if board is not None:
            project_all(places.queue, board.adapter)

    project_to_board()  # the pre-existing queue state, before this loop has run a single turn

    while True:
        # Checked before waking: a count already at its cap needs no wait to know that.
        if iteration >= bound.max_iterations:
            return LoopReport(
                steps=tuple(steps),
                stopped=StopReason.MAX_ITERATIONS,
                spend_usd=spend.total_since(start_moment, resolved_spend_log),
            )

        if iteration == 0:
            poll_board_if_due()  # a command that arrived before the loop started still applies
            wake_reason = WakeReason.STARTUP
        else:
            wake_reason = _await_wake(
                places,
                wake,
                last_head=last_head,
                last_heartbeat=last_heartbeat,
                now_fn=now_fn,
                sleep_fn=sleep_fn,
                on_tick=poll_board_if_due,
            )

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
        project_to_board()  # every outcome, not only advanced -- a stall belongs on the board too
        steps.append(LoopStep(wake=wake_reason, record=record))
        iteration += 1
        last_head = _queue_head(places.queue)
        last_heartbeat = now_fn()


def _places_for(repo: Path, queue: Path | None, workspace: Path | None, transcripts: Path | None = None) -> Places:
    """Resolve `--queue`/`--workspace` against the `repo` positional, deriving the rest of
    `Places` exactly as `Places.local` would when they agree, and keying `workspace_lock` to the
    workspace's own path (matching the convention both `scripts/run_a2web_turn.py` and
    `yoselabs/factory-state`'s driver already use by hand) when they differ.

    `ledger` and `queue_lock` are always under the queue -- there is no caller, real or
    hypothetical, that has ever wanted the ledger to live anywhere other than beside the backlog
    it records turns against.

    K D033: a queue given as a subdirectory of the workspace (`--workspace <ws> --queue
    <ws>/.factory`, `Places.nested`'s own shape) is not a repository of its own -- `resolved_queue
    / LOCK` would compute a lock path under a nonexistent `.git`, and would key it differently from
    `resolved_workspace / LOCK`, defeating `_workspace_lock`'s one-tree-one-lock collapse for the
    one shape that most needs it (queue-side and workspace-side operations landing in the same
    tree). Detected by containment rather than by a separate flag: this is the only shape in which
    `resolved_queue` sits inside `resolved_workspace`, since the fully-separate-repositories shape
    below has no reason for one to nest inside the other.

    K D034: `transcripts`, given (`--transcripts-dir`), resolves and overrides whichever `Places`
    shape was picked above -- one `replace()` regardless of branch, rather than three call sites
    each threading it through. Omitted, each branch below defaults `transcripts` to its own
    `ledger`, exactly as before this parameter existed.
    """
    resolved_queue = (queue or repo).resolve()
    resolved_workspace = (workspace or repo).resolve()
    if resolved_queue == resolved_workspace:
        places = Places.local(resolved_queue)
    elif resolved_queue.is_relative_to(resolved_workspace):
        ledger = resolved_queue / RUNS
        places = Places(
            queue=resolved_queue,
            ledger=ledger,
            queue_lock=resolved_workspace / LOCK,
            workspace=resolved_workspace,
            workspace_lock=resolved_workspace / LOCK,
            transcripts=ledger,
        )
    else:
        ledger = resolved_queue / RUNS
        places = Places(
            queue=resolved_queue,
            ledger=ledger,
            queue_lock=resolved_queue / LOCK,
            workspace=resolved_workspace,
            workspace_lock=resolved_workspace / LOCK,
            transcripts=ledger,
        )
    if transcripts is not None:
        places = replace(places, transcripts=transcripts.resolve())
    return places


def main(argv: Sequence[str] | None = None, *, unattended: bool = False) -> int:
    """Run the loop, by default against one local repository playing all `Places` roles
    (`Places.local`) — but `--queue`/`--workspace` may split queue from workspace.

    Cross-machine and non-default executor configuration are still left to a caller that imports
    `run_loop` directly. Cross-*repo* is not, as of `give-the-entrypoint-a-cross-repo-surface`:
    `--queue`/`--workspace` (task 1.1) let this entrypoint itself be that caller for the one shape
    that turned out to matter -- a private queue and a public workspace (K D026) -- without
    growing into a general-purpose launcher. Omitting both keeps every existing behavior identical
    to `Places.local(repo)`, byte for byte (see `_places_for` below).

    `unattended` gates the isolation posture (`IsolationPolicy`, below) — D022 §3 defers a
    program-wide cost ceiling on the premise a human is present to watch and interrupt a run; that
    premise holds for a person typing this command and does not hold for a scheduler invoking it
    with nobody there. Rather than re-litigate the deferral, this keeps interactive use exactly as
    it was (`unattended=False`, the default `main()` still gets when called directly) and switches
    posture only on the path a scheduler actually takes — `scheduled_main()`, below. (A prior
    revision of this docstring also had `unattended` make `--spend-ceiling-usd` required; that flag
    is deleted — K D034 — and no longer part of what `unattended` gates.)

    The same `unattended` signal now also gates publication (`pin-the-executor-and-close-the-push-
    grant`): D022 §2 granted push for a turn a human is watching, and an unattended run committing
    with nobody watching is not that case — the `--publish` flag reopens it explicitly for a given
    invocation, and does nothing on the interactive path, which was never gated on it.
    """
    import argparse
    import shlex
    import sys

    from yosefactory.executor import claude
    from yosefactory.runtime.isolation import IsolationPolicy

    parser = argparse.ArgumentParser(prog="python -m yosefactory.runtime.loop")
    parser.add_argument("repo", type=Path, nargs="?", default=Path("."))
    parser.add_argument(
        "--queue",
        type=Path,
        default=None,
        help="Defaults to `repo`. Where backlog items, questions and the ledger live. Combined "
        "with --workspace, lets queue and workspace be different repositories (K D026) -- see "
        "containerized-loop/cross-repo-invocation.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Defaults to `repo`. Where the agent works, is verified, and commits. See --queue.",
    )
    parser.add_argument(
        "--transcripts-dir",
        type=Path,
        default=None,
        help="Where the executor's raw `*.stream.jsonl` lands (K D034), separately from the "
        "ledger's `.start`/terminal-record files, which always ride --queue's own commit. Defaults "
        "to the ledger (today's location, unchanged) -- set this to a directory outside the "
        "workspace to retain transcripts past the workspace container's own lifetime.",
    )
    parser.add_argument("--owner", default="loop")
    parser.add_argument("--skill", type=Path, default=Path("workflows/turn-skill.md"))
    parser.add_argument("--max-iterations", type=int, required=True)
    parser.add_argument(
        "--cost-ceiling-usd",
        type=float,
        default=None,
        help="A single TURN's budget (Guardrails.cost_ceiling_usd, enforced post-hoc by the "
        "executor's own --max-budget-usd). Omitted, a turn is unbounded by cost. (A prior revision "
        "of this flag also interacted with a now-deleted --spend-ceiling-usd, the loop's cumulative "
        "ceiling across iterations -- removed, K D034: it never once fired in production and the "
        "cross-run cumulative view it was reaching for is explicitly unwanted. This flag is the "
        "only remaining spend enforcement point and is otherwise unchanged.)",
    )
    parser.add_argument(
        "--test-command",
        type=str,
        default=None,
        help="Overrides the built-in DEFAULT_TEST_COMMAND ('pytest -q') for the verification gate "
        "-- e.g. --test-command \"make check\" for a workspace whose own gate is not pytest. Split "
        "with shlex.split. Omitted, behavior is unchanged.",
    )
    parser.add_argument("--heartbeat-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument(
        "--board-repo",
        default=None,
        help="'owner/name' -- when given, wires a GitHubIssuesAdapter into the loop (turn-loop/"
        "board-wiring). Omitted by default: the loop runs exactly as it did before this existed.",
    )
    parser.add_argument("--board-poll-seconds", type=int, default=60, help="Ignored unless --board-repo is given.")
    parser.add_argument("--board-actor", default="board", help="Ignored unless --board-repo is given.")
    parser.add_argument(
        "--board-allowed-actor",
        action="append",
        default=None,
        metavar="LOGIN",
        help="A GitHub login permitted to originate board commands (repeatable). Required if "
        "--board-repo is given -- ingest() takes no default allowlist, since workspaces are "
        "public and an ungated intake turns a stranger's issue into a work item.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Reopen the push grant for an unattended invocation (scheduled_main). Ignored on the "
        "interactive path, which always publishes and was never gated on it. Absent, an unattended "
        "run commits locally and does not push -- see runtime.loop.main's own docstring and "
        "containerized-loop/unattended-publication-posture.",
    )
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    places = _places_for(repo, args.queue, args.workspace, args.transcripts_dir)
    if unattended:
        # D022 §2 granted push for a turn a human is watching. `scheduled_main` (below) is the one
        # caller with `unattended=True`, so this branch is the entire reach of the new default --
        # the interactive path above is untouched and keeps publishing both places unconditionally,
        # exactly as `Places.local` always has.
        places = replace(places, publish_workspace=args.publish, publish_queue=args.publish)
    limits = Guardrails(
        window=10,
        wall_clock_seconds=45 * 60,
        turn_ceiling=40,
        grace_seconds=20,
        question_deadline_hours=24,
        max_attempts=3,
        # A single TURN's ceiling. `None` (the default) sends no flag, exactly as before this existed.
        cost_ceiling_usd=args.cost_ceiling_usd,
    )
    test_command = tuple(shlex.split(args.test_command)) if args.test_command is not None else DEFAULT_TEST_COMMAND
    # `unattended` signals a human is or is not present (D022). The posture correct for a person on
    # their own laptop is not
    # the posture correct for a process nobody is watching: `isolated` (safe-mode,
    # `--permission-mode manual`) denies every tool call pending an approval nobody unattended can
    # give. `scheduled_main` -- the container's own entrypoint -- goes through here with
    # `unattended=True`. See `run-the-loop-inside-the-container` design.md D1/D3 for the boundary
    # this relies on instead: container mount topology, not this policy, is what keeps an
    # unattended run from reaching anything outside its workspace.
    policy = (
        IsolationPolicy(
            isolated=False,
            workspace_scoped=True,
            opt_out_reason=(
                "unattended (scheduler/container) invocation: mount topology, not this policy, "
                "bounds what the run can reach outside its workspace; workspace_scoped + a "
                "non-denying permission mode is required for real work with no human present to "
                "approve a prompt"
            ),
        )
        if unattended
        else IsolationPolicy(isolated=True)
    )

    board_config: BoardConfig | None = None
    if args.board_repo is not None:
        from yosefactory.board.github import GitHubIssuesAdapter

        if not args.board_allowed_actor:
            parser.error("--board-allowed-actor is required (repeatable) when --board-repo is given")

        board_config = BoardConfig(
            adapter=GitHubIssuesAdapter(args.board_repo),
            allowed_actors=frozenset(args.board_allowed_actor),
            actor=args.board_actor,
            poll_seconds=args.board_poll_seconds,
        )

    def executor(
        frame: Mapping[str, Any],
        workspace: Path,
        limits: Guardrails,
        *,
        run_id: str,
        runs_dir: Path,
        transcripts_dir: Path,
        context: Mapping[str, Any] | None = None,
        invocation: Any = None,
    ) -> Any:
        return claude.run(
            frame,
            workspace,
            limits,
            run_id=run_id,
            runs_dir=runs_dir,
            transcripts_dir=transcripts_dir,
            context=context,
            invocation=invocation,
            policy=policy,
        )

    report = run_loop(
        places,
        executor,
        limits=limits,
        owner=args.owner,
        skill=args.skill,
        bound=LoopBound(max_iterations=args.max_iterations),
        wake=WakeConfig(heartbeat_seconds=args.heartbeat_seconds, poll_seconds=args.poll_seconds),
        board=board_config,
        test_command=test_command,
        # `run_loop`'s own `isolated` parameter (default True) is a SEPARATE value from `policy`
        # above -- it feeds `take_turn`'s turn-record field, not the executor invocation. Left
        # unwired, every record says `isolated: true` regardless of what posture actually ran --
        # found reading the first real container receipt's own ledger record (D1 built the
        # `workspace_scoped` posture but never wired this half, so the record contradicted the
        # invocation that produced it). `run-guardrails/agent-isolation`'s own requirement is that
        # an opted-out run is identifiable afterwards from its record; this line is what makes
        # that true for `unattended` runs.
        isolated=policy.isolated,
    )
    sys.stdout.write(
        f"stopped: {report.stopped.value}; iterations: {len(report.steps)}; spend: ${report.spend_usd:.4f}\n"
    )
    for step in report.steps:
        sys.stdout.write(f"  {step.wake.value:16} {step.record.outcome.value:14} {step.record.note}\n")

    # unstick-the-backlog / S1021: `stall.py` was already correct and already invocable on its own —
    # nothing in this repository's own process ever called it, so a freeze reported STALLED forever
    # and nobody saw it. This entrypoint (interactively, and via `scheduled_main` --
    # `ops/launchd/dev.yosefactory.loop.plist.template` already names it) is what a scheduler
    # actually runs, so its exit code is where "loud" has to land without inventing a new workflow.
    verdict = stall.detect(places.ledger)
    sys.stdout.write(verdict.report() + "\n")
    return {stall.Status.OK: 0, stall.Status.STALLED: 1, stall.Status.STARVED: 2}[verdict.status]


def scheduled_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for a scheduler (`launchd`, `cron`) — never a person.

    Identical to `main()` except `unattended=True`: the isolation posture switches to
    `workspace_scoped` (no human present to approve a tool prompt), and publication defaults to
    declined unless `--publish` is given — see `main`'s own docstring for why both live on this
    entrypoint and not on `main` itself. This is the function
    `ops/launchd/dev.yosefactory.loop.plist.template` names, via the `yosefactory-loop-scheduled`
    console script (`pyproject.toml`) — a scheduler invokes a stable installed script, never
    `python -m` re-typed inside a plist.

    (A prior revision also made `--spend-ceiling-usd` mandatory here and nowhere else — that flag
    is deleted, K D034, and this entrypoint no longer requires anything beyond what `main()` already
    requires; see design.md of `delete-the-cumulative-spend-ceiling` for why `scheduled_main` still
    exists once that was its most-cited reason.)
    """
    return main(argv, unattended=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
