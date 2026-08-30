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
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
from uuid import uuid4

from yosefactory.executor.invocation import Invocation
from yosefactory.executor.outcome import RunOutcome, RunResult
from yosefactory.protocol import backlog, question
from yosefactory.protocol.eventlog import Declaration, FoldedLog, LogError
from yosefactory.protocol.eventlog import load as load_log
from yosefactory.protocol.turn import BlockedKind, EnforcedBy, FailureKind, Outcome, TurnRecord
from yosefactory.runtime import runs, spend, verify
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
    """The five roles one `repo: Path` used to play at once, named separately.

    `queue` — backlog items and questions. `ledger` — turn records, always nested under `queue`
    (the ledger is platform bookkeeping, never the agent's own work, so `commit()` can always reach
    it through `queue`). `workspace` — the agent's cwd, the subject of the verification gate and of
    `dirty`, and the destination of the agent's own checkpoint commits, which this module never makes
    and never rewrites — it marks exactly one, `HEAD` at the moment the `done` gate passes, by
    amendment (`_deliver_workspace`), which is the whole of `commit-attribution`'s reach here.
    `transcripts` — where the raw `*.stream.jsonl` the executor writes lands (K D034); see below.

    Two locks, not one, because a single tree made them look like one job: `queue_lock` serializes
    picking and claiming against one backlog; `workspace_lock` serializes agent execution and commits
    against one working tree, keyed by the workspace's own identity rather than by which queue
    dispatched the turn — two different queues pointed at the same workspace still must not overlap.

    `publish_queue`/`publish_workspace` — whether `publish()` may push that place at all, decided per
    role because a queue you own and a workspace you are a guest in are different cases (D022 grants
    push; this is whether a given turn may decline it, not a change to the grant). Default `True`:
    an unstated choice publishes both, exactly as every turn did before these fields existed.

    `transcripts` is never left unset — every constructor below defaults it to `ledger`, today's
    location, byte for byte, because that is where `runs_dir` has always pointed the executor's
    transcript write. (A `Path | None` field defaulting itself in `__post_init__` was the first
    shape tried; `ty` cannot see through that to know the field is never `None` by the time a
    caller reads it, so every reader would need its own narrowing. Resolving it once, in each
    constructor, keeps the field itself simply `Path`.) K D034 names the defect this seam exists to
    fix: under `Places.nested`, `ledger` sits inside the workspace, so `ensure_transcripts_ignored`
    correctly keeps the transcript from dirtying the gate's tree, but the same exclusion means the
    transcript is never committed and dies with the workspace's container. A caller that wants
    transcripts retained somewhere durable and outside the workspace — the runner repository, per
    D034's "Observability" — sets `transcripts` to that location; every existing caller, having
    never set it, is unaffected.
    """

    queue: Path
    ledger: Path
    queue_lock: Path
    workspace: Path
    workspace_lock: Path
    transcripts: Path
    publish_queue: bool = True
    publish_workspace: bool = True

    @classmethod
    def local(cls, repo: Path) -> Places:
        """One repository plays all five roles, exactly as every turn has run until now."""
        return cls(
            queue=repo,
            ledger=repo / RUNS,
            queue_lock=repo / LOCK,
            workspace=repo,
            workspace_lock=repo / LOCK,
            transcripts=repo / RUNS,
        )

    @classmethod
    def nested(cls, workspace: Path, *, queue_subdir: str = ".factory", transcripts: Path | None = None) -> Places:
        """K D033: the queue lives *inside* the workspace's own repository, in a subdirectory --
        not in a repository of its own. One workspace, one commit history, one push target; a
        second workspace's queue is a different repository entirely and can never see this one's
        items (`pick()` has no cross-workspace reach, so two workspaces can never pay for the same
        item -- that is the whole point of D033).

        `queue_lock` and `workspace_lock` both resolve to `workspace`'s own lock file, never to one
        computed under `queue` -- `queue_subdir` is not itself a repository and has no `.git` to
        anchor a lock under. This is the same collapse `Places.local` already relies on when
        `queue == workspace`; `_workspace_lock` tests exactly this equality to skip a redundant
        re-lock, and it applies unchanged here because the two paths, though different directories,
        share one working tree.

        `transcripts` (K D034): omitted, it defaults to `ledger` -- today's location, so this
        parameter is inert until a caller supplies one. A caller that does supply one (typically a
        directory outside `workspace` entirely, e.g. the runner repository) gets raw transcripts
        retained there instead of excluded and lost with the workspace's container.
        """
        queue = workspace / queue_subdir
        ledger = queue / RUNS
        return cls(
            queue=queue,
            ledger=ledger,
            queue_lock=workspace / LOCK,
            workspace=workspace,
            workspace_lock=workspace / LOCK,
            transcripts=transcripts if transcripts is not None else ledger,
        )


def spend_log_for(places: Places) -> Path:
    """Where this turn's own queue commits its spend row — sibling to `ledger/runs/`, inside
    `places.queue` rather than resolved from this package's own installed location.

    `runtime.spend.SPEND_LOG` (the module's own default) resolves via `paths.repo_root()` from
    `spend.py`'s `__file__` — deliberately the platform's own checkout, not whatever foreign
    workspace a turn happens to be working on (that module's docstring). But "the platform's own
    checkout" and "the repository `turn.commit()` actually writes into" are only the same
    directory under `Places.local` (one repo playing every role). The moment `queue` and the
    installed package diverge — `run-the-loop-inside-the-container`'s own topology, where the
    loop's queue is a bind-mounted `/data/workspace` and the package lives read-only-to-uid-1000
    under `/app` — a spend row written to the package's own location can never be staged by a
    commit that only ever touches `places.queue` (`commit()`, below): `git commit -- <paths>`
    ignores anything outside the pathspecs it was given, and a path outside the repo it runs in
    is not even a valid pathspec. Scoping every write this module makes to `places.queue` keeps
    "spend belongs to the platform" true in the sense that matters here — the platform's own
    bookkeeping repository, distinct from `places.workspace` under cross-repo operation — while
    making it the same repository `commit()` stages into, which is the property this change needs.
    """
    return places.ledger.parent / "spend.jsonl"


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

    D030: `context` is a fourth, separate thing -- what attempts before this one produced
    (`backlog.context()`), folded from the item's own log. Kept beside `frame` rather than inside
    it for the same reason `invocation` is kept out: mixing what was *asked* with what was
    *discovered* makes the frame unrecoverable as a record of authored intent.

    K D034: `transcripts_dir` names where the raw `*.stream.jsonl` lands, separately from
    `runs_dir` (the `.start`/terminal-record stream, which always rides `places.ledger` and the
    turn's own commit). The two coincide under every caller that has not set `Places.transcripts`
    -- see `Places.__post_init__` -- so this parameter is inert until one does.
    """

    def __call__(
        self,
        frame: Mapping[str, Any],
        workspace: Path,
        limits: Guardrails,
        *,
        run_id: str,
        runs_dir: Path,
        transcripts_dir: Path,
        context: Mapping[str, Any] | None = None,
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
    """`ready`, or `doing` whose most recent event is `gate_rejected`.

    S236/resume-gate-rejected-item: ADR-0015 chose `gate_rejected: doing -> doing` so a rejection
    stays retryable within the same attempt, and `backlog-item-format`'s own spec already says an
    item may carry any number of `gate_rejected` records while remaining `doing` -- nothing acted on
    that until now. The second case resumes the existing lease (`take_turn` skips the claim step for
    it) rather than flowing back through `ready`, which is the only way `attempt` stays unmoved.
    Waking a snoozed item is a sweeper's job (`wake_snoozed`, four-dead-ends) -- it runs in the same
    pre-classification step as `apply_answers`/`reclaim_expired`, so a woken item is `ready` and
    already admitted by the check above before this function is next consulted.
    """
    if item.state == "ready":
        return True
    return item.state == "doing" and item.records[-1]["event"] == "gate_rejected"


def in_flight(item: FoldedLog) -> bool:
    """`claimed` or `doing` -- genuinely being worked on right now, or was until its lease expires,
    at which point `reclaim_expired` (below) resolves it before this is ever consulted (S1021)."""
    return item.state in ("claimed", "doing")


def should_plan(backlog_items: Sequence[FoldedLog]) -> bool:
    """Plan when nothing is ready and nothing is live in-flight.

    Only `claimed`/`doing` suppress planning -- unstick-the-backlog / S1021, kept unchanged by
    four-dead-ends even though `blocked`, `snoozed` and retryable `failed` now have working sweepers
    (`sweep_deadlines`, `wake_snoozed`, `retry_failed`): a bound that resolves *eventually* is still
    not "in flight" in the sense this predicate means, and widening it back would reopen the freeze
    S1021 found -- one item with a bound that has not fired yet would again forbid all future work.
    `falsified`/`needs_split` still have no route back at all. A backlog holding only such litter is
    planned around exactly like an empty backlog already is: bounded by `LoopBound.max_iterations`,
    not by this predicate. See `decisions/0012-lease-reclaim-and-should-plan-narrowed-to-in-flight.md`.
    """
    return not any(in_flight(item) for item in backlog_items)


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
        resolution = {"qid": path.stem, "by": str(closed["event"])}
        # S1038/D030: the answer's text, not only a pointer to the question that carries it --
        # copied here, at the moment the question closes, rather than read cross-file when
        # `backlog.context()` folds the item later. The question log keeps the canonical
        # `answered` record; this is a read-only echo, never the thing a second decision is made
        # from.
        answer = closed.get("answer")
        if answer is not None:
            resolution["answer"] = answer
        append(
            item_path,
            backlog.ITEM,
            {"event": "unblocked", "resolution": resolution},
            actor=actor,
        )
        moved.append(item_id)
    return moved


def _poison_if_exhausted(item_path: Path, folded: FoldedLog, *, actor: str, max_attempts: int) -> None:
    """Escalate a `failed` item straight to `poison` when it must not be retried or has used its budget.

    Reads two fields the format has required since it was defined and no code read until
    unstick-the-backlog: `retryable` is the agent's own judgment that trying again is pointless,
    taken at face value once; `attempt` is the same counter `claimed` increments on every claim (and
    `reclaim_expired`'s own claims), so a crash loop and a repeatedly-declined proposal are capped by
    one number. A no-op when the item is not `failed` or carries no `failed` record (never true for
    a just-appended `failed` event, but `folded` is passed rather than re-derived so this stays a
    pure function of its argument).
    """
    if folded.state != "failed":
        return
    last = backlog.failure(folded)
    if last is None:
        return
    attempt = int(last.get("attempt", 0))
    if last.get("retryable") is False or attempt >= max_attempts:
        append(item_path, backlog.ITEM, {"event": "poisoned", "attempts": attempt}, actor=actor)


def reclaim_expired(repo: Path, *, actor: str, now: datetime, max_attempts: int) -> list[Path]:
    """Reclaim every `claimed`/`doing` item whose lease has expired, or poison it if attempts are used up.

    Runs in the same deterministic, agent-free sweep as `apply_answers`, before classification, so a
    reclaimed item is visible to `should_plan`/`eligible` in the same turn that reclaimed it (S1021:
    `expires_at` was written and read by nothing before this).

    D002: never edits the `claimed` record -- `reclaimed` only ever appends. Safe against a "dead"
    turn that is not actually dead: this only ever appends too, so if the original turn is alive and
    later appends its own event from `claimed`/`doing`, that append still succeeds locally against
    its own clone. What is at risk is not correctness but that turn's own eventual `push_repo`, which
    may be rejected as non-fast-forward once this reclaim has landed first -- a lost turn, not
    corrupted state (design.md's own section on this).
    """
    touched: list[Path] = []
    for path in sorted((repo / ITEMS).glob("*.jsonl")):
        item = backlog.load(path)
        if item.state not in ("claimed", "doing"):
            continue
        current_lease = backlog.lease(item)
        if current_lease is None:
            continue
        expires_at = datetime.fromisoformat(str(current_lease["expires_at"]))
        if now < expires_at:
            continue
        attempt = int(current_lease["attempt"])
        owner = str(current_lease["owner"])
        if attempt >= max_attempts:
            append(
                path,
                backlog.ITEM,
                {
                    "event": "failed",
                    "reason": f"lease held by {owner!r} expired on attempt {attempt}/{max_attempts}; no further reclaim",
                    "attempt": attempt,
                    "retryable": False,
                },
                actor=actor,
            )
            append(path, backlog.ITEM, {"event": "poisoned", "attempts": attempt}, actor=actor)
        else:
            append(
                path,
                backlog.ITEM,
                {"event": "reclaimed", "reason": "lease expired", "expired_owner": owner, "expired_attempt": attempt},
                actor=actor,
            )
        touched.append(path)
    return touched


def wake_snoozed(repo: Path, *, actor: str, now: datetime) -> list[Path]:
    """Wake every `snoozed` item whose `scheduled_for` has passed. Same deterministic, agent-free
    sweep as `apply_answers`/`reclaim_expired` -- no model call decides whether a clock has passed.

    four-dead-ends: `woke` (`snoozed` -> `ready`) has been declared since the format was defined and
    fired by nothing (`eligible()`'s own docstring used to say so). This is the sweeper.
    """
    touched: list[Path] = []
    for path in sorted((repo / ITEMS).glob("*.jsonl")):
        item = backlog.load(path)
        if item.state != "snoozed":
            continue
        due = backlog.scheduled_for(item)
        if due is None or now < datetime.fromisoformat(str(due)):
            continue
        append(path, backlog.ITEM, {"event": "woke", "cause": "scheduled_for elapsed"}, actor=actor)
        touched.append(path)
    return touched


def sweep_deadlines(repo: Path, *, actor: str, now: datetime) -> list[Path]:
    """Resolve every `blocked` item whose bound has elapsed.

    The bound is read from wherever `backlog-item-format`'s "Blocked means blocked until" says it
    lives: the block's own `awaiting.deadline`/`on_timeout` for `kind: item`, or the linked question
    (`ref`) for `kind: question`/`kind: request` -- never a second copy kept on the item.

    `escalate` and `default:<x>` both resolve the block the same way the format's own "The deadline
    fires" scenario states, without branching on policy: `unblocked` with `resolution: "timeout"`,
    returning to the `return_to` stored at block time. Only `abandon:<reason>` diverges -- there is no
    `return_to` worth resuming behind a deliberate give-up, so the item goes straight to `abandoned`
    instead. For a question-backed block, the question itself is closed first (`timed_out`, carrying
    the policy and, for `default:<x>`, the supplied answer) so it stops reading as open.

    `nudge_at` (a list of pre-deadline reminder points) is deliberately not fired here: this
    repository has no notification channel for a sweep to write through (`grep` for one before this
    change found none), and inventing a fake delivery would be worse than the gap it papers over. It
    stays a recorded intent, unacted on, until a channel exists to act through.
    """
    touched: list[Path] = []
    for path in sorted((repo / ITEMS).glob("*.jsonl")):
        item = backlog.load(path)
        if item.state != "blocked":
            continue
        block = backlog.awaiting(item)
        if block is None:
            continue
        question_path: Path | None = None
        if block.get("kind") == "item":
            deadline_raw = block.get("deadline")
            policy = block.get("on_timeout")
        else:
            question_path = repo / QUESTIONS / f"{block.get('ref')}.jsonl"
            if not question_path.exists():
                continue
            asked = question.load(question_path)
            if question.outcome(asked) is not None:
                continue  # already closed -- `apply_answers` resolves this one, not this sweep
            deadline_raw = question.deadline(asked)
            policy = question.on_timeout(asked)
        if deadline_raw is None or policy is None or now < datetime.fromisoformat(str(deadline_raw)):
            continue
        if question_path is not None:
            answer = policy.split(":", 1)[1] if policy.startswith("default:") else None
            append(
                question_path,
                question.QUESTION,
                {"event": "timed_out", "policy": policy, "answer": answer},
                actor=actor,
            )
            touched.append(question_path)
        if policy.startswith("abandon:"):
            append(
                path,
                backlog.ITEM,
                {"event": "abandoned", "reason": f"blocked deadline elapsed: {policy.split(':', 1)[1]}"},
                actor=actor,
            )
        else:
            append(path, backlog.ITEM, {"event": "unblocked", "resolution": "timeout"}, actor=actor)
        touched.append(path)
    return touched


def retry_failed(repo: Path, *, actor: str, max_attempts: int) -> list[Path]:
    """Return every retryable `failed` item to `ready`, under the same cap `_poison_if_exhausted`
    already enforces on the other side.

    Any item still sitting in `failed` (not `poisoned`) was, by construction, `retryable: true` and
    under `max_attempts` at the moment it failed -- `_poison_if_exhausted` poisons every other case
    immediately, in the same turn the `failed` event lands. The check here is defensive, not
    load-bearing, against that invariant changing later. `retried` carries no `attempt` of its own:
    the count lives on `claimed` and survives every trip back through `ready` already
    (`backlog.claims()`), and this sweep does not touch it -- an item that has exhausted its budget
    must not become eligible again by another door.
    """
    touched: list[Path] = []
    for path in sorted((repo / ITEMS).glob("*.jsonl")):
        item = backlog.load(path)
        if item.state != "failed":
            continue
        last = backlog.failure(item)
        if last is None or last.get("retryable") is not True or int(last.get("attempt", 0)) >= max_attempts:
            continue
        append(path, backlog.ITEM, {"event": "retried", "cause": "retryable failure under the attempt cap"}, actor=actor)
        touched.append(path)
    return touched


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


def _head_sha(repo: Path, env: dict[str, str]) -> str | None:
    completed = _git(repo, ["rev-parse", "HEAD"], env, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else None


def _deliver_workspace(repo: Path, run_id: str, head_before: str | None) -> str:
    """Amend the workspace's boundary commit with the platform's trailers, after the gate passes.

    `may_write_done` already requires the tree clean before this can be reached, so there is nothing
    left to commit — only the commit already at `HEAD` to mark. That is the one commit this run has
    gate-backed evidence about; every earlier checkpoint the agent made this turn is untouched
    (commit-attribution: amend, never a new commit, never anything but `HEAD`).

    `head_before`, read once under the workspace lock before the executor ran: if `HEAD` never moved,
    this turn produced no workspace commit and none is invented — `""` records that honestly.

    Hooks are skipped on the amend (`--no-verify`): the tree is unchanged from what already passed
    them when the agent's own commit ran; re-running them asks the same question again at this
    platform's expense, in a repository it does not own, for a reason unrelated to the diff.
    """
    env = {**os.environ, "PREK_ALLOW_NO_CONFIG": "1"}
    head_after = _head_sha(repo, env)
    if head_after is None or head_after == head_before:
        return ""
    message = _git(repo, ["log", "-1", "--format=%B", head_after], env).stdout
    marked = _with_platform_trailers(repo, message, run_id, env)
    handle = NamedTemporaryFile("w", suffix=".msg", delete=False, encoding="utf-8")
    try:
        handle.write(marked)
        handle.close()
        amended = _git(repo, ["commit", "--amend", "--no-verify", "-F", handle.name], env, check=False)
    finally:
        Path(handle.name).unlink(missing_ok=True)
    if amended.returncode != 0:
        tail = (amended.stdout or amended.stderr).strip().splitlines()[-1:] or ["no output"]
        raise TurnError(f"workspace delivery refused: {tail[0]}")
    delivered = _head_sha(repo, env)
    if delivered is None:
        raise TurnError("workspace delivery amended but HEAD is unreadable")
    return delivered


class PublicationFailed(RuntimeWarning):
    """A push was attempted and rejected. Reported once here; D022 forbids retrying it blind."""


@dataclass(frozen=True, slots=True)
class PublishResult:
    """What happened when one repository was asked to publish. Never raised — always returned."""

    repo: Path
    status: str  # "pushed" | "skipped" | "rejected" | "declined"
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
    # The flag is checked before push_repo runs at all, for either place — a declined place's own
    # remote state is never consulted, so "declined" can never share a code path with "skipped".
    workspace_result = (
        push_repo(places.workspace)
        if places.publish_workspace
        else PublishResult(repo=places.workspace, status="declined", detail="publication declined for this place")
    )
    queue_result = (
        push_repo(places.queue)
        if places.publish_queue
        else PublishResult(repo=places.queue, status="declined", detail="publication declined for this place")
    )
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

    # Guaranteed before anything is written to the ledger this turn (S237): under `Places.local`,
    # `places.transcripts` (defaulting to `places.ledger`, K D034) nests inside `places.workspace`,
    # the tree `verify.tree_clean` inspects at the `done` gate. Without this, a raw transcript this
    # turn's own executor writes is an untracked file the gate counts as the agent's uncommitted
    # work. Guards `places.transcripts` specifically, not `places.ledger` -- the two diverge exactly
    # when a caller has pointed transcripts outside the workspace, and it is that configuration
    # `ensure_transcripts_ignored`'s own no-op (runs_dir not relative to workspace) is meant to
    # cover.
    runs.ensure_transcripts_ignored(places.transcripts, places.workspace)

    with single_flight(places.queue_lock):
        # Declared before any work, and committed immediately: a turn that dies leaves a marker with
        # no record, which reads back as a gap rather than as a turn nobody knows happened. Committed
        # rather than left in the tree because the `done` gate requires a clean tree, and a turn's own
        # bookkeeping must not read as the agent having left work half-finished.
        slug = runs.open_run(places.ledger, run_id, started)
        commit(places.queue, [places.ledger / f"{slug}.start"], f"turn({run_id}): declared", run_id=run_id)
        # Both sweeps are deterministic and agent-free (turn-cycle: "Answers waiting in the
        # repository are applied before classification"). Committed immediately, before anything
        # else this turn does -- the claim commit just below already establishes that a write left
        # uncommitted here is a write `_finish`'s later `tree_is_dirty` check would misattribute to
        # the agent under `Places.local` (queue == workspace), and unstick-the-backlog / S1021 found
        # `apply_answers`'s own writes had been suffering exactly that since it was written: its
        # return value naming the items it moved was discarded, so those items' `unblocked` lines
        # landed on disk and were never named in any commit's pathspec.
        unblocked_ids = apply_answers(places.queue, actor=owner)
        reclaimed_paths = reclaim_expired(places.queue, actor=owner, now=started, max_attempts=limits.max_attempts)
        # four-dead-ends: three more agent-free sweeps, same step, same commit -- run after the two
        # above so each sees what the earlier ones already moved (`sweep_deadlines` must not act on
        # an item `apply_answers` just unblocked; `retry_failed` must not act on one `reclaim_expired`
        # just poisoned). Every sweep re-reads the item fresh, so this ordering is a read-time fact,
        # not a hidden shared-state dependency.
        woken_paths = wake_snoozed(places.queue, actor=owner, now=started)
        deadline_paths = sweep_deadlines(places.queue, actor=owner, now=started)
        retried_paths = retry_failed(places.queue, actor=owner, max_attempts=limits.max_attempts)
        swept = (
            [places.queue / ITEMS / f"{item_id}.jsonl" for item_id in unblocked_ids]
            + reclaimed_paths
            + woken_paths
            + deadline_paths
            + retried_paths
        )
        if swept:
            commit(
                places.queue,
                swept,
                f"sweep({run_id}): {len(swept)} item(s) unblocked, reclaimed, woken, deadlined or retried",
                run_id=run_id,
            )
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
                    planning_frame,
                    places.workspace,
                    limits,
                    run_id=run_id,
                    runs_dir=places.ledger,
                    transcripts_dir=places.transcripts,
                    invocation=invocation,
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
                    max_attempts=limits.max_attempts,
                )
                publish(places, record)
                return record

        item_path = places.queue / ITEMS / f"{target.id}.jsonl"
        if target.state == "doing":
            # resume-gate-rejected-item / S236: `eligible()` admitted this target because its most
            # recent event is `gate_rejected`, not because it is `ready`. ADR-0015 keeps that
            # retryable within the same attempt, so no new `claimed`/`started` is appended here --
            # the item is already `doing`, already committed, already has a lease. `attempt` is read
            # from that lease rather than recomputed, which is what keeps it from moving.
            existing_lease = backlog.lease(target)
            assert existing_lease is not None  # noqa: S101 -- `eligible()` only admits a `doing` item with a lease on record
            attempt = int(existing_lease["attempt"])
            loaded = target
        else:
            # `target` is `ready` here, so `backlog.lease(target)` reads None and a computation
            # keyed off it always restarts at 1 -- exactly the gap unstick-the-backlog / S1021
            # found: the `attempt` field could never exceed 1 in production, so nothing gated on it
            # could ever fire. `backlog.claims()` counts the item's whole history instead, so the
            # count survives every `released`/`reclaimed` trip back through `ready`.
            attempt = backlog.claims(target) + 1
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
            loaded = backlog.load(item_path)

        frame = backlog.frame(loaded)
        # D030: folded from the same log `frame` was, never merged into it -- the executor's second,
        # separate channel for what attempts before this one produced.
        context = backlog.context(loaded)
        with _workspace_lock(places):
            # Read before the executor touches anything: the only fact `_deliver_workspace` needs to
            # tell "this turn made a commit" from "HEAD is whatever an earlier turn left."
            workspace_head_before = _head_sha(places.workspace, dict(os.environ))
            result = executor(
                frame,
                places.workspace,
                limits,
                run_id=run_id,
                runs_dir=places.ledger,
                transcripts_dir=places.transcripts,
                context=context,
                invocation=invocation,
            )
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
                max_attempts=limits.max_attempts,
                workspace_head_before=workspace_head_before,
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
    max_attempts: int,
    workspace_head_before: str | None = None,
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
            model=result.model,
            effort=result.effort,
            total_cost_usd=result.usage.total_cost_usd,
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
            model=result.model,
            effort=result.effort,
            total_cost_usd=result.usage.total_cost_usd,
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
            model=result.model,
            effort=result.effort,
            total_cost_usd=result.usage.total_cost_usd,
        )

    assert item_path is not None  # noqa: S101 — narrowed by `planning`, which ty cannot see through
    event = proposed[0]
    workspace_commit = ""
    if event["event"] == "done":
        claim = verify.Claim(run_id=run_id, terminal_verdict=result.outcome.value)
        gate = verify.may_write_done(places.workspace, claim, test_command=test_command)
        if not gate.passed:
            # S1037/D030: the rejection must reach the item, not only the ledger's `TurnRecord`,
            # so the next attempt inherits it via `backlog.context()` instead of re-reading a
            # byte-identical frame. `item_path` is already in `touched`, so this lands in the same
            # commit `failed()` below makes -- no new commit call, no new attempt-budget spend
            # (`gate_rejected` does not change state and is never read by `_poison_if_exhausted`).
            lease = backlog.lease(backlog.load(item_path))
            attempt_no = lease["attempt"] if lease is not None else None
            append(
                item_path,
                backlog.ITEM,
                {"event": "gate_rejected", "report": gate.report(), "attempt": attempt_no},
                actor=owner,
            )
            return failed(gate.report())
        # After the gate, never before: `_deliver_workspace` marks the commit the gate just
        # certified, which is only a real fact once the gate has actually passed.
        workspace_commit = _deliver_workspace(places.workspace, run_id, workspace_head_before)

    try:
        folded = append(item_path, backlog.ITEM, event, actor=owner)
    except (LogError, TurnError) as exc:
        return failed(f"proposal refused: {exc}")

    # unstick-the-backlog / S1021: an agent-reported `failed` that is not retryable, or that has
    # used its attempt budget, escalates straight to `poison` in the same turn -- appended to the
    # same `item_path` already in `touched`/`paths` below, so it lands in the same commit.
    _poison_if_exhausted(item_path, folded, actor=owner, max_attempts=max_attempts)
    folded = backlog.load(item_path)  # re-fold: may now read `poison` rather than `failed`

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
        model=result.model,
        effort=result.effort,
        workspace_commit=workspace_commit,
        total_cost_usd=result.usage.total_cost_usd,
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
    model: str = "",
    effort: str = "",
    workspace_commit: str = "",
    total_cost_usd: float | None = None,
) -> TurnRecord:
    """Write the run record, the spend row that belongs beside it, and commit both together.

    `total_cost_usd` is `None` only for the one caller with no executor invocation to attribute a
    cost to (`take_turn`'s `nothing-ready` path) — every `_dispose` branch threads
    `result.usage.total_cost_usd` here, zero included, because zero is a real value
    (`runtime.spend.record`'s own docstring) and every one of those branches is reached strictly
    after any gate this turn's event required (`_dispose`'s "done" branch calls `verify.
    may_write_done` — which demands a clean `places.workspace` — before it can reach any return
    that lands here). That ordering is load-bearing, not incidental: this function is the *only*
    place either write happens, so as long as every call site is post-gate, no write this function
    makes can ever be the reason a gate call sees a dirty tree it should not.

    Ordered internally the same way, for the one case where `places.queue == places.workspace`
    (`Places.local`) and so every write below lands in the same tree `dirty` is about: `dirty` is
    computed from the tree *before* this turn's own bookkeeping touches it, so this function's own
    writes can never be mistaken for the agent's.
    """
    runs_dir = places.ledger
    # The agent's own tree, never the queue's — `dirty` means the agent left work half-done, and
    # when queue and workspace differ the queue's own bookkeeping (still uncommitted at this
    # point) would otherwise be misread as the agent's mess. Read before this function writes
    # anything of its own (the run record below, the spend row after it) — under `Places.local`
    # those writes land in this same tree, and a dirty flag computed after them would be reporting
    # on this function's own bookkeeping rather than on what the agent left behind.
    dirty = tree_is_dirty(places.workspace, ignore=runs_dir)

    # Committed by `turn.commit()` below — never here — the same function ADR-0004 names as the
    # sole composer of the platform's trailers. Attempted after the gate every "done" path already
    # ran and after `dirty` above, so a spend-write failure costs this turn only its own row, never
    # the ledger record, the item transition, or the workspace commit `_deliver_workspace` already
    # made before any of this function's callers were reached (commit-the-spend-row-inside-the-
    # turn's priority: workspace delivery > ledger record > spend row).
    spend_log = spend_log_for(places)
    spend_detail = ""
    if total_cost_usd is not None:
        try:
            spend.record(total_cost_usd, run_id=run_id, log_path=spend_log)
        except OSError as exc:
            spend_detail = f"spend row not recorded: {exc}"
    full_note = f"{note} [{spend_detail}]" if spend_detail else note

    record = TurnRecord(
        run_id=run_id,
        started_at=started.isoformat(),
        ended_at=utc_now(),
        outcome=outcome,
        enforced_by=enforced_by,
        dirty=dirty,
        isolated=isolated,
        note=full_note,
        failure_kind=failure_kind,
        blocked_kind=blocked_kind,
        # "" on a turn no executor ran for (nothing-ready) -- there is no run to attribute a model
        # or effort to. Every turn that did start an executor threads `result.model`/`result.effort`
        # here instead of leaving the default.
        model=model,
        effort=effort,
        workspace_commit=workspace_commit,
    )
    written = runs.append(runs_dir, slug, record)
    # Always the queue: every path this turn commits — the item, a raised question, the ledger
    # record itself, the spend row — is platform bookkeeping. The workspace's own delivery already
    # happened, if at all, in `_dispose` before this call, via `_deliver_workspace` rather than
    # this function.
    #
    # `spend_log` is appended unconditionally rather than guarded by an `outcome` or
    # `total_cost_usd` check: `commit()` already filters its pathspecs to what `.exists()` (a
    # `nothing-ready` turn, which never wrote a row this turn, simply contributes no diff for this
    # path — not an error, not a missing file worth naming). Every branch above that did write it
    # is what makes this one `commit()` call the place the spend row and the run record it
    # describes become atomic — either both land in this commit or neither does.
    commit(
        places.queue,
        [*paths, written, written.with_suffix(".start"), spend_log],
        f"turn({run_id}): {outcome.value} — {full_note}",
        run_id=run_id,
    )
    return record
