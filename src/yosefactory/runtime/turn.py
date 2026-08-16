"""One turn: read the repository, do exactly one thing, record it, commit, exit.

There is no workflow object here and there is deliberately nothing for one to attach to (S173). The
phase is read from the backlog's state, never declared, so ordering is a consequence rather than a
list someone maintains.

The split this module exists to enforce (architecture.md §1): the agent proposes **one** typed event
and the code disposes of it. Appending *is* the check — the candidate log is folded before it
replaces the real one — so nothing here holds a second copy of which transitions are legal, and a
rejected proposal leaves the item byte-for-byte as it was. That last property is what makes a failed
turn safe to retry.

Identifiers are generated without reading anything (S186). A scheme that reads the current maximum is
a lock in disguise: two planning turns both read the same highest id and write the same new one.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import warnings
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from yosefactory.executor.invocation import Invocation
from yosefactory.executor.outcome import RunOutcome, RunResult
from yosefactory.protocol import backlog, question
from yosefactory.protocol.eventlog import Declaration, FoldedLog, LogError
from yosefactory.protocol.eventlog import load as load_log
from yosefactory.protocol.turn import BlockedKind, EnforcedBy, FailureKind, Outcome, TurnRecord
from yosefactory.runtime import runs, verify
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.supervise import single_flight, tree_is_dirty

# `asked`'s first production writer (protocol/question.py's KINDS and rule have existed, unreached,
# since the format was defined). A permission denial is the harness refusing an action, not an
# explicit spend ask the agent frames itself — `gate-failed` over `cost-approval`. Nothing in `src/`
# branches on `kind` today (checked: `question.blocking_by_design` has no production caller), so this
# is documentation, not behaviour, and is re-arguable the day a consumer reads it.
_DENIAL_QUESTION_KIND = "gate-failed"

ITEMS = Path("backlog/items")
QUESTIONS = Path("questions")
RUNS = Path("ledger") / runs.STREAM_DIRNAME
LOCK = Path(".git") / "yosefactory-turn.lock"

# Frozen (commit-attribution spec). Every commit the platform ever writes is compared against every
# other, so changing either splits one author into two in history that D002 forbids correcting.
PLATFORM_CO_AUTHOR = "yosefactory <yosefactory@yoselabs.dev>"
RUN_TRAILER_KEY = "Yosefactory-Run"

# The event log's own fields. An agent that supplies one is refused rather than overridden: dedup and
# replay order both key on them, and they may not come from the component S098 measured as unreliable.
RESERVED = ("event_id", "ts", "actor")

_STAMP = "%Y%m%dT%H%M%SZ"

DEFAULT_PLANNING_FRAME: Mapping[str, Any] = {
    "goal": "Emit the next work item, or several, for this loop.",
    "method": "Read the repository. Propose `created` events; do not act on them.",
    "assumptions": "Nothing is in flight; a planned item is inert until a later turn claims it.",
}


class TurnError(RuntimeError):
    """The turn refused to proceed. Never raised for an agent's bad proposal — that is an outcome."""


@dataclass(frozen=True, slots=True)
class Places:
    """The four roles one `repo: Path` used to play at once, named separately.

    `queue` — backlog items and questions. `ledger` — turn records, always nested under `queue`
    (the ledger is platform bookkeeping, never the agent's own work, so `commit()` can always reach
    it through `queue`). `workspace` — the agent's cwd, the subject of the verification gate and of
    `dirty`, and the destination of the agent's own commits, which this module never makes and never
    marks (`commit-attribution`'s writer rule is `turn.commit()` only).

    Two locks, not one, because a single tree made them look like one job: `queue_lock` serializes
    picking and claiming against one backlog; `workspace_lock` serializes agent execution and commits
    against one working tree, keyed by the workspace's own identity rather than by which queue
    dispatched the turn — two different queues pointed at the same workspace still must not overlap.
    """

    queue: Path
    ledger: Path
    queue_lock: Path
    workspace: Path
    workspace_lock: Path

    @classmethod
    def local(cls, repo: Path) -> Places:
        """One repository plays all four roles, exactly as every turn has run until now."""
        return cls(
            queue=repo,
            ledger=repo / RUNS,
            queue_lock=repo / LOCK,
            workspace=repo,
            workspace_lock=repo / LOCK,
        )


@contextmanager
def _workspace_lock(places: Places) -> Iterator[None]:
    """Acquire the workspace lock, unless it is the queue lock already held around this call.

    `fcntl.flock` locks an open file description, not a process — re-opening and re-locking the same
    path from the same process blocks (or fails under `LOCK_NB`) rather than no-op'ing. `Places.local`
    points both locks at one file on purpose, so path equality is the dodge: it removes the need to
    know whether `flock` is reentrant rather than answering that question.
    """
    if places.workspace_lock == places.queue_lock:
        yield
    else:
        with single_flight(places.workspace_lock):
            yield


class Executor(Protocol):
    """The seam. Three things, three parameters: what the work is, how to run it, what bounds it.

    The skill and the proposal path travel in `invocation` and never in `frame` — the frame is
    D019's unit of falsification and lands in the item's permanent trail, where a file path is not a
    claim that can be wrong, only one that can go stale.
    """

    def __call__(
        self,
        frame: Mapping[str, Any],
        workspace: Path,
        limits: Guardrails,
        *,
        run_id: str,
        runs_dir: Path,
        invocation: Invocation | None = None,
    ) -> RunResult: ...


# The executor's two failing vocabularies join here. Its run-level stops carry no typed kind of their
# own, which is why a set mirroring only its typed kinds would lose the starved-versus-broken
# distinction entirely. Total over `RunOutcome` and asserted so by test: a new vendor stop must fail
# a test rather than silently record no reason.
_RUN_LEVEL_KIND: dict[RunOutcome, FailureKind | None] = {
    RunOutcome.SUCCESS: None,
    # Null on both: the reason they carry is a `blocked_kind`, not a failure kind — routed to
    # `Outcome.BLOCKED` in `_dispose` before this mapping is ever consulted for them.
    RunOutcome.NEEDS_APPROVAL: None,
    RunOutcome.REFUSED: None,
    RunOutcome.BUDGET_EXHAUSTED: FailureKind.BUDGET_EXHAUSTED,
    RunOutcome.TURN_LIMIT: FailureKind.TURN_LIMIT,
    RunOutcome.CANCELLED: FailureKind.CANCELLED,
    RunOutcome.FAILED: None,
}


def failure_kind_of(result: RunResult) -> FailureKind | None:
    """The reason the executor reported, typed. Never inferred from an exit status or a message.

    `RunOutcome.FAILED` maps to null here and defers to the typed kind beside it, which is where the
    executor puts the reason when the run itself is what failed.
    """
    run_level = _RUN_LEVEL_KIND[result.outcome]
    if run_level is not None or result.failure_kind is None:
        return run_level
    try:
        return FailureKind(result.failure_kind.value)
    except ValueError as exc:
        raise TurnError(f"executor failure kind {result.failure_kind.value!r} has no recordable equivalent") from exc


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why a proposal was not written. The item is unchanged; the turn records `failed`."""

    detail: str


def utc_now(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).isoformat()


def new_item_id(moment: datetime | None = None) -> str:
    """`itm-<stamp>-<8 hex>`, matching the question format. Generated blind — nothing is read."""
    return f"itm-{(moment or datetime.now(UTC)).strftime(_STAMP)}-{secrets.token_hex(4)}"


def new_run_id(moment: datetime | None = None) -> str:
    return f"turn-{(moment or datetime.now(UTC)).strftime(_STAMP)}-{secrets.token_hex(4)}"


def new_question_id(moment: datetime | None = None) -> str:
    """`q-<stamp>-<8 hex>`, matching `questions/README.md`'s correlation id shape."""
    return f"q-{(moment or datetime.now(UTC)).strftime(_STAMP)}-{secrets.token_hex(4)}"


def append(path: Path, declaration: Declaration, payload: Mapping[str, Any], *, actor: str) -> FoldedLog:
    """Append one event, or leave the log untouched and raise.

    The candidate is folded in a temporary file and renamed over the log only once the fold accepts
    it, so an illegal transition, an unknown event or a missing field costs the log nothing.
    """
    for field in RESERVED:
        if field in payload:
            raise TurnError(f"{field!r} is generated by the turn; an event may not carry its own")
    if not payload.get("event"):
        raise TurnError("an event must name itself")

    record = {"event_id": uuid4().hex, "ts": utc_now(), "actor": actor, **payload}
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    candidate = path.with_name(path.name + ".candidate")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(existing + json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    try:
        folded = load_log(candidate, declaration, log_id=path.stem)
    except LogError:
        candidate.unlink(missing_ok=True)
        raise
    candidate.replace(path)
    return folded


def items(repo: Path) -> list[FoldedLog]:
    return [backlog.load(path) for path in sorted((repo / ITEMS).glob("*.jsonl"))]


def eligible(item: FoldedLog) -> bool:
    """`ready` and nothing else. Waking a snoozed item is a sweeper's job and there is no sweeper."""
    return item.state == "ready"


def should_plan(backlog_items: Sequence[FoldedLog]) -> bool:
    """Plan only when nothing is in flight.

    Work that exists but is blocked or snoozed is not an argument for making more of it — that is how
    a backlog fills with slop while the real item waits on an answer. `nothing-ready` is the honest
    record of that state, and it is the one architecture.md §8 needs in order to see a green stall.
    """
    return not any(not item.terminal for item in backlog_items)


def pick(candidates: Sequence[FoldedLog]) -> FoldedLog | None:
    """Highest priority, then lowest id. Deterministic, so two turns pick the same item and the
    claim — not the ordering — is what resolves the collision."""
    ranked = sorted(candidates, key=lambda item: (-int(backlog.priority(item) or 0), item.id))
    return ranked[0] if ranked else None


def apply_answers(repo: Path, *, actor: str) -> list[str]:
    """Unblock every item whose question has closed. Returns the item ids that moved.

    The target state is read from the block's own `awaiting.return_to` by the fold, never recomputed
    here — it was decided when the block was written.

    No steering inbox is read: no such format exists in this repository (design-e2e.md §1 describes
    one and nothing implements it). Recorded as a gap rather than invented.
    """
    moved: list[str] = []
    for path in sorted((repo / QUESTIONS).glob("*.jsonl")):
        asked = question.load(path)
        closed = question.outcome(asked)
        if closed is None:
            continue
        item_id = str(question.asked(asked)["item"])
        item_path = repo / ITEMS / f"{item_id}.jsonl"
        if not item_path.exists() or backlog.load(item_path).state != "blocked":
            continue
        append(
            item_path,
            backlog.ITEM,
            {"event": "unblocked", "resolution": {"qid": path.stem, "by": str(closed["event"])}},
            actor=actor,
        )
        moved.append(item_id)
    return moved


def read_proposal(path: Path, *, planning: bool) -> list[dict[str, Any]] | Refusal:
    """One JSON object, or — for a planning turn only — a list of them.

    A missing file is a refusal rather than an absence: an agent that wrote nothing did not decline,
    it failed, and the two must not read alike.
    """
    if not path.exists():
        return Refusal("the agent wrote no proposal")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Refusal(f"proposal is not valid JSON: {exc.msg}")

    events = payload if isinstance(payload, list) else [payload]
    if not events:
        return Refusal("proposal carries no event")
    if not planning and len(events) != 1:
        return Refusal(f"an acting turn proposes exactly one event; got {len(events)}")
    for event in events:
        if not isinstance(event, dict):
            return Refusal(f"an event must be a JSON object, got {type(event).__name__}")
        if not event.get("event"):
            return Refusal("an event must name itself")
        for field in RESERVED:
            if field in event:
                return Refusal(f"an event may not carry its own {field!r}")
    return events


def outcome_for(state: str) -> Outcome:
    """What the item's new state means for the turn. `done` is not the only way to advance —
    `falsified` advanced the knowledge, which is what this platform exists to accumulate."""
    if state == "blocked":
        return Outcome.BLOCKED
    if state in ("failed", "poison"):
        return Outcome.FAILED
    return Outcome.ADVANCED


def _with_platform_trailers(repo: Path, message: str, run_id: str, env: dict[str, str]) -> str:
    """Append the platform's trailers using git's own parser (commit-attribution spec).

    Hand-assembly would reimplement rules git already encodes — whether a trailer block exists,
    whether a blank line is needed, whether the body's last paragraph already parses as trailers —
    and getting any of them wrong produces a message that reads right to a human and parses wrong to
    a tool, which is the one failure this mechanism cannot afford. No fallback: an unmarked commit
    enters the record as evidence of hand-driven work and D002 forbids correcting it afterwards.
    """
    argv = [
        "git",
        "interpret-trailers",
        "--trailer",
        f"Co-Authored-By: {PLATFORM_CO_AUTHOR}",
        "--trailer",
        f"{RUN_TRAILER_KEY}: {run_id}",
    ]
    completed = subprocess.run(  # noqa: S603
        argv,
        cwd=repo,
        env=env,
        input=message,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise TurnError(f"trailer composition refused: {(completed.stderr or completed.stdout).strip()}")
    return completed.stdout


def commit(repo: Path, paths: Sequence[Path], message: str, *, run_id: str) -> None:
    """Explicit pathspecs on every git call. The index is shared; `commit -- <paths>` ignores it."""
    present = [path for path in paths if path.exists()]
    if not present:
        return
    relative = [str(path.relative_to(repo)) for path in present]
    env = {**os.environ, "PREK_ALLOW_NO_CONFIG": "1"}
    message = _with_platform_trailers(repo, message, run_id, env)
    _git(repo, ["add", "--", *relative], env)
    committed = _git(repo, ["commit", "-m", message, "--", *relative], env, check=False)
    if committed.returncode != 0:
        _git(repo, ["restore", "--staged", "--", *relative], env, check=False)
        tail = (committed.stdout or committed.stderr).strip().splitlines()[-1:] or ["no output"]
        raise TurnError(f"commit refused: {tail[0]}")


def _git(repo: Path, argv: list[str], env: dict[str, str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603
        ["git", *argv],  # noqa: S607
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise TurnError(f"git {argv[0]} failed: {(completed.stderr or completed.stdout).strip()}")
    return completed


class PublicationFailed(RuntimeWarning):
    """A push was attempted and rejected. Reported once here; D022 forbids retrying it blind."""


@dataclass(frozen=True, slots=True)
class PublishResult:
    """What happened when one repository was asked to publish. Never raised — always returned."""

    repo: Path
    status: str  # "pushed" | "skipped" | "rejected"
    detail: str = ""


def _current_branch(repo: Path) -> str | None:
    completed = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], dict(os.environ), check=False)
    if completed.returncode != 0:
        return None
    branch = completed.stdout.strip()
    return None if not branch or branch == "HEAD" else branch


def _has_remote(repo: Path, name: str = "origin") -> bool:
    completed = _git(repo, ["remote", "get-url", name], dict(os.environ), check=False)
    return completed.returncode == 0


def push_repo(repo: Path) -> PublishResult:
    """Push the current branch to `origin`, by explicit refspec. No force, no tags, no new remote.

    A missing remote or a detached HEAD is a skip — D022 grants push to an already-configured
    remote, so a repository with none is out of scope rather than misconfigured, and there is no
    branch name to push from a detached HEAD. Only an attempted, rejected push is `rejected`.
    """
    if not _has_remote(repo):
        return PublishResult(repo=repo, status="skipped", detail="no origin remote configured")
    branch = _current_branch(repo)
    if branch is None:
        return PublishResult(repo=repo, status="skipped", detail="HEAD is detached; nothing named to push")
    completed = _git(repo, ["push", "origin", f"{branch}:{branch}"], dict(os.environ), check=False)
    if completed.returncode == 0:
        return PublishResult(repo=repo, status="pushed", detail=branch)
    tail = (completed.stderr or completed.stdout).strip().splitlines()[-1:] or ["no output"]
    return PublishResult(repo=repo, status="rejected", detail=tail[0])


def publish(places: Places, record: TurnRecord) -> tuple[PublishResult, PublishResult] | None:
    """Push workspace, then queue — only for a turn that advanced, and never inside its transaction.

    `None` for every other outcome: `blocked` carries no verification receipt for the workspace
    (`may_write_done` only ever runs on a `done` proposal), so publishing it would publish on trust
    rather than on the evidence `advanced` requires. Workspace before queue, so a published record
    never points at a commit that is not yet public (`turn-publication`).
    """
    if record.outcome is not Outcome.ADVANCED:
        return None
    workspace_result = push_repo(places.workspace)
    queue_result = push_repo(places.queue)
    for result in (workspace_result, queue_result):
        if result.status == "rejected":
            warnings.warn(f"publish: {result.repo} push rejected: {result.detail}", PublicationFailed, stacklevel=2)
    return workspace_result, queue_result


def take_turn(
    places: Places,
    executor: Executor,
    *,
    limits: Guardrails,
    owner: str,
    skill: Path,
    planning_frame: Mapping[str, Any] = DEFAULT_PLANNING_FRAME,
    loop: str = "default",
    proposal_dir: Path | None = None,
    test_command: tuple[str, ...] = verify.DEFAULT_TEST_COMMAND,
    isolated: bool = True,
    cross_machine: bool = False,
    cas_push: bool = False,
    phase: str | None = None,
    now: datetime | None = None,
) -> TurnRecord:
    """Acquire, classify, do one item, record, commit, exit. Returns the record it wrote.

    `phase` exists only to be refused. The phase is a consequence of the backlog's state, and a caller
    that names it has a different design in mind (S173).

    A single repository playing all four `places` roles (`Places.local`) behaves exactly as every
    turn has until now — one lock, one tree, one commit path.
    """
    if phase is not None:
        raise TurnError("the phase is derived from item state and cannot be supplied")
    if cross_machine and not cas_push:
        raise TurnError(
            "cross-machine operation needs the compare-and-swap claim push, which is not enabled; "
            "a single-machine turn is protected by the lock and a multi-machine turn is not"
        )

    started = now or datetime.now(UTC)
    run_id = new_run_id(started)
    scratch = proposal_dir or Path(os.environ.get("TMPDIR", "/tmp"))  # noqa: S108
    # Outside both repositories, so a killed run cannot leave a tree dirty and fail another worker's
    # commit — the tree-wide stash S184 records makes that everyone's problem, not just this turn's.
    proposal_path = scratch / f"{run_id}.proposal.json"

    with single_flight(places.queue_lock):
        # Declared before any work, and committed immediately: a turn that dies leaves a marker with
        # no record, which reads back as a gap rather than as a turn nobody knows happened. Committed
        # rather than left in the tree because the `done` gate requires a clean tree, and a turn's own
        # bookkeeping must not read as the agent having left work half-finished.
        slug = runs.open_run(places.ledger, run_id, started)
        commit(places.queue, [places.ledger / f"{slug}.start"], f"turn({run_id}): declared", run_id=run_id)
        apply_answers(places.queue, actor=owner)
        present = items(places.queue)
        target = pick([item for item in present if eligible(item)])

        if target is None and not should_plan(present):
            record = _finish(
                places,
                started,
                run_id,
                slug,
                Outcome.NOTHING_READY,
                EnforcedBy.HARNESS,
                note="nothing eligible; no agent was started",
                paths=[],
                isolated=isolated,
            )
            publish(places, record)
            return record

        invocation = Invocation(skill=skill, vocabulary=backlog.VOCABULARY_SPEC, proposal_path=proposal_path)

        if target is None:
            with _workspace_lock(places):
                result = executor(
                    planning_frame, places.workspace, limits, run_id=run_id, runs_dir=places.ledger, invocation=invocation
                )
                record = _dispose(
                    places,
                    started,
                    run_id,
                    slug,
                    result,
                    item_path=None,
                    proposal_path=proposal_path,
                    owner=owner,
                    loop=loop,
                    isolated=isolated,
                    test_command=test_command,
                    question_deadline_hours=limits.question_deadline_hours,
                )
                publish(places, record)
                return record

        item_path = places.queue / ITEMS / f"{target.id}.jsonl"
        attempt = int((backlog.lease(target) or {}).get("attempt", 0)) + 1
        append(
            item_path,
            backlog.ITEM,
            {
                "event": "claimed",
                "owner": owner,
                "expires_at": (started + timedelta(seconds=limits.wall_clock_seconds)).isoformat(),
                "attempt": attempt,
            },
            actor=owner,
        )
        append(item_path, backlog.ITEM, {"event": "started"}, actor=owner)
        # Committed before the agent runs: a crash from here on is legible as claimed-and-abandoned
        # rather than never-started, which is the state architecture.md §4 found v1 had deleted.
        commit(places.queue, [item_path], f"claim({target.id}): attempt {attempt} by {owner}", run_id=run_id)

        frame = backlog.frame(backlog.load(item_path))
        with _workspace_lock(places):
            result = executor(frame, places.workspace, limits, run_id=run_id, runs_dir=places.ledger, invocation=invocation)
            record = _dispose(
                places,
                started,
                run_id,
                slug,
                result,
                item_path=item_path,
                proposal_path=proposal_path,
                owner=owner,
                loop=loop,
                isolated=isolated,
                test_command=test_command,
                question_deadline_hours=limits.question_deadline_hours,
            )
            publish(places, record)
            return record


def _dispose(
    places: Places,
    started: datetime,
    run_id: str,
    slug: str,
    result: RunResult,
    *,
    item_path: Path | None,
    proposal_path: Path,
    owner: str,
    loop: str,
    isolated: bool,
    test_command: tuple[str, ...],
    question_deadline_hours: int,
) -> TurnRecord:
    planning = item_path is None
    subject = "planning" if planning else item_path.stem
    touched = [] if item_path is None else [item_path]

    def failed(detail: str, kind: FailureKind | None = None) -> TurnRecord:
        return _finish(
            places,
            started,
            run_id,
            slug,
            Outcome.FAILED,
            EnforcedBy.HARNESS,
            note=f"{subject}: {detail}",
            paths=touched,
            isolated=isolated,
            failure_kind=kind,
        )

    def blocked(detail: str, kind: BlockedKind | None) -> TurnRecord:
        paths = touched
        # `needs_approval` is resumable (`protocol/turn.py`'s `RESUMABLE`), unlike `refused`, so it
        # is the one blocking ending that must leave something an answer can resolve. A planning turn
        # holds no item to suspend — there is nothing to raise the question against — so it falls
        # through to the ledger-only record below exactly as `refused` always does.
        if kind is BlockedKind.NEEDS_APPROVAL and item_path is not None:
            qid = new_question_id(started)
            question_path = places.queue / QUESTIONS / f"{qid}.jsonl"
            append(
                question_path,
                question.QUESTION,
                {
                    "event": "asked",
                    "qid": qid,
                    "item": item_path.stem,
                    "kind": _DENIAL_QUESTION_KIND,
                    "to": "denis",
                    "text": detail,
                    "answer_type": "choice",
                    "options": ["yes", "no"],
                    "return_to": "doing",
                    "deadline": (started + timedelta(hours=question_deadline_hours)).isoformat(),
                    "on_timeout": "default:no",
                },
                actor=owner,
            )
            append(
                item_path,
                backlog.ITEM,
                {
                    "event": "blocked",
                    "awaiting": {
                        "kind": "question",
                        "ref": qid,
                        "who": owner,
                        "since": utc_now(started),
                        "return_to": "doing",
                        "nudge_at": [],
                    },
                },
                actor=owner,
            )
            paths = [*touched, question_path]
        return _finish(
            places,
            started,
            run_id,
            slug,
            Outcome.BLOCKED,
            EnforcedBy.HARNESS,
            note=f"{subject}: {detail}",
            paths=paths,
            isolated=isolated,
            blocked_kind=kind,
        )

    if result.outcome is not RunOutcome.SUCCESS:
        # The reason travels in the typed field, so the note no longer restates it. A reason narrated
        # into free text is a reason that was known and then discarded at the moment it became durable.
        # The outcome itself comes from the executor's own declared mapping rather than being asserted
        # here: a permission denial and a refusal are the run stopping, not the run breaking, and a
        # branch that sent every non-success ending to `failed` is what left `blocked_kind` unwritable.
        detail = f"executor reported {result.outcome.value}: {result.detail}"
        if result.protocol_outcome is Outcome.BLOCKED:
            return blocked(detail, result.blocked_kind)
        return failed(detail, failure_kind_of(result))

    proposed = read_proposal(proposal_path, planning=planning)
    if isinstance(proposed, Refusal):
        return failed(proposed.detail)

    if planning:
        written: list[Path] = []
        for event in proposed:
            path = places.queue / ITEMS / f"{new_item_id()}.jsonl"
            try:
                append(path, backlog.ITEM, {"loop": loop, **event}, actor=owner)
            except (LogError, TurnError) as exc:
                for done in written:
                    done.unlink(missing_ok=True)
                return failed(f"proposal refused: {exc}")
            written.append(path)
        return _finish(
            places,
            started,
            run_id,
            slug,
            Outcome.ADVANCED,
            EnforcedBy.AGENT,
            note=f"planned {len(written)} item(s): {', '.join(path.stem for path in written)}",
            paths=written,
            isolated=isolated,
        )

    assert item_path is not None  # noqa: S101 — narrowed by `planning`, which ty cannot see through
    event = proposed[0]
    if event["event"] == "done":
        claim = verify.Claim(run_id=run_id, terminal_verdict=result.outcome.value)
        gate = verify.may_write_done(places.workspace, claim, test_command=test_command)
        if not gate.passed:
            return failed(gate.report())

    try:
        folded = append(item_path, backlog.ITEM, event, actor=owner)
    except (LogError, TurnError) as exc:
        return failed(f"proposal refused: {exc}")

    return _finish(
        places,
        started,
        run_id,
        slug,
        outcome_for(folded.state),
        EnforcedBy.AGENT,
        note=f"{subject}: {event['event']} -> {folded.state}",
        paths=[item_path],
        isolated=isolated,
    )


def _finish(
    places: Places,
    started: datetime,
    run_id: str,
    slug: str,
    outcome: Outcome,
    enforced_by: EnforcedBy,
    *,
    note: str,
    paths: Sequence[Path],
    isolated: bool,
    failure_kind: FailureKind | None = None,
    blocked_kind: BlockedKind | None = None,
) -> TurnRecord:
    runs_dir = places.ledger
    record = TurnRecord(
        run_id=run_id,
        started_at=started.isoformat(),
        ended_at=utc_now(),
        outcome=outcome,
        enforced_by=enforced_by,
        # The agent's own tree, never the queue's — `dirty` means the agent left work half-done, and
        # when queue and workspace differ the queue's own bookkeeping (still uncommitted at this
        # point) would otherwise be misread as the agent's mess.
        dirty=tree_is_dirty(places.workspace, ignore=runs_dir),
        isolated=isolated,
        note=note,
        failure_kind=failure_kind,
        blocked_kind=blocked_kind,
    )
    written = runs.append(runs_dir, slug, record)
    # Always the queue: every path this turn commits — the item, a raised question, the ledger record
    # itself — is platform bookkeeping. The agent's own workspace commits are its own, made and left
    # unmarked outside this function (commit-attribution: the platform's trailers are never the
    # agent's to carry).
    commit(places.queue, [*paths, written, written.with_suffix(".start")], f"turn({run_id}): {outcome.value} — {note}", run_id=run_id)
    return record
