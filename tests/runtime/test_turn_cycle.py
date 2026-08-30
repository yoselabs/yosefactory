"""One turn of the reducer.

The acceptance test is `test_two_turns_share_nothing_but_the_repository`: turn one plans from an
empty backlog, turn two — a separate call, sharing no state — picks up what it committed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from yosefactory.executor.invocation import Invocation
from yosefactory.executor.outcome import FailureKind, RunOutcome, RunResult, Usage
from yosefactory.protocol import backlog, question
from yosefactory.protocol.eventlog import LogError
from yosefactory.protocol.turn import BlockedKind, EnforcedBy, Outcome, resumable, starved
from yosefactory.protocol.turn import FailureKind as ProtocolFailureKind
from yosefactory.runtime import turn
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.runs import read_window
from yosefactory.runtime.supervise import single_flight

TRUE_COMMAND = ("true",)
FALSE_COMMAND = ("false",)
SKILL = Path("workflows/turn-skill.md")

FRAME = {"goal": "g", "method": "m", "assumptions": "a"}
CREATED = {"event": "created", "loop": "l", "frame": FRAME}


def git(repo: Path, *args: str) -> str:
    binary = shutil.which("git")
    assert binary is not None
    completed = subprocess.run([binary, *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
    return completed.stdout.strip()


@pytest.fixture
def limits() -> Guardrails:
    return Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1, question_deadline_hours=24, max_attempts=3)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / turn.ITEMS).mkdir(parents=True)
    (root / turn.QUESTIONS).mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    return root


def bare_remote(tmp_path: Path, name: str = "remote") -> Path:
    remote = tmp_path / name
    remote.mkdir()
    git(remote, "init", "--bare", "-q")
    return remote


def set_origin(repo: Path, remote: Path) -> None:
    git(repo, "remote", "add", "origin", str(remote))


def diverged_remote(tmp_path: Path, name: str, branch: str) -> Path:
    """A bare remote pre-loaded with a commit the eventual pusher does not have — a guaranteed reject."""
    remote = bare_remote(tmp_path, name)
    scratch = tmp_path / f"{name}-scratch"
    scratch.mkdir()
    git(scratch, "init", "-q")
    git(scratch, "checkout", "-q", "-b", branch)
    git(scratch, "config", "user.email", "t@example.invalid")
    git(scratch, "config", "user.name", "T")
    (scratch / "other.txt").write_text("other\n", encoding="utf-8")
    git(scratch, "add", "other.txt")
    git(scratch, "commit", "-q", "-m", "unrelated")
    git(scratch, "push", str(remote), f"{branch}:{branch}")
    return remote


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A second repository, with no queue directories of its own — the agent's foreign target."""
    root = tmp_path / "workspace"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    return root


class FakeExecutor:
    """Writes a scripted proposal where the turn asked for it, and remembers being called."""

    def __init__(
        self,
        proposal: Any = None,
        *,
        outcome: RunOutcome = RunOutcome.SUCCESS,
        raw: str | None = None,
        kind: FailureKind | None = None,
        total_cost_usd: float = 0.0,
    ) -> None:
        self.proposal = proposal
        self.raw = raw
        self.outcome = outcome
        self.kind = kind if kind is not None else FailureKind.CRASH
        self.total_cost_usd = total_cost_usd
        self.calls: list[Mapping[str, Any]] = []
        self.contexts: list[Mapping[str, Any] | None] = []
        self.invocations: list[Invocation | None] = []
        self.log_at_call: list[str] = []
        self.workspaces: list[Path] = []
        self.transcripts_dirs: list[Path] = []

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
    ) -> RunResult:
        self.contexts.append(context)
        self.calls.append(frame)
        self.invocations.append(invocation)
        self.log_at_call.append(git(workspace, "log", "--oneline"))
        self.workspaces.append(workspace)
        self.transcripts_dirs.append(transcripts_dir)
        assert invocation is not None and invocation.proposal_path is not None
        path = invocation.proposal_path
        if self.raw is not None:
            path.write_text(self.raw, encoding="utf-8")
        elif self.proposal is not None:
            path.write_text(json.dumps(self.proposal), encoding="utf-8")
        return RunResult(
            outcome=self.outcome,
            usage=Usage(total_cost_usd=self.total_cost_usd),
            transcript_path=transcripts_dir / f"{run_id}.stream.jsonl",
            exit_code=0,
            dirty=False,
            failure_kind=self.kind if self.outcome is not RunOutcome.SUCCESS else None,
            detail="",
        )


def take(repo: Path, executor: Any, limits: Guardrails, **kwargs: Any) -> Any:
    kwargs.setdefault("test_command", TRUE_COMMAND)
    return turn.take_turn(
        turn.Places.local(repo), executor, limits=limits, owner="tester", skill=SKILL, proposal_dir=repo.parent, **kwargs
    )


def take_split(
    queue: Path,
    workspace: Path,
    executor: Any,
    limits: Guardrails,
    *,
    publish_queue: bool = True,
    publish_workspace: bool = True,
    **kwargs: Any,
) -> Any:
    """Queue and workspace as two distinct repositories, each with its own lock file."""
    kwargs.setdefault("test_command", TRUE_COMMAND)
    places = turn.Places(
        queue=queue,
        ledger=queue / turn.RUNS,
        queue_lock=queue / turn.LOCK,
        workspace=workspace,
        workspace_lock=workspace / turn.LOCK,
        transcripts=queue / turn.RUNS,
        publish_queue=publish_queue,
        publish_workspace=publish_workspace,
    )
    return turn.take_turn(places, executor, limits=limits, owner="tester", skill=SKILL, proposal_dir=queue.parent, **kwargs)


def seed_item(repo: Path, *, state: str = "ready") -> Path:
    path = repo / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(path, backlog.ITEM, CREATED, actor="fixture")
    if state == "ready":
        return path
    turn.append(path, backlog.ITEM, {"event": "claimed", "owner": "o", "expires_at": "later", "attempt": 1}, actor="fixture")
    turn.append(path, backlog.ITEM, {"event": "started"}, actor="fixture")
    if state == "blocked":
        turn.append(
            path,
            backlog.ITEM,
            {
                "event": "blocked",
                "awaiting": {
                    "kind": "question",
                    "ref": "q-1",
                    "who": "denis",
                    "since": "now",
                    "return_to": "ready",
                    "nudge_at": [],
                    "deadline": "later",
                    "on_timeout": "escalate",
                },
            },
            actor="fixture",
        )
    return path


def seed_question(repo: Path, item_id: str, *, answered: bool) -> Path:
    path = repo / turn.QUESTIONS / "q-20260816T171204Z-3f9a2c1d.jsonl"
    turn.append(
        path,
        question.QUESTION,
        {
            "event": "asked",
            "item": item_id,
            "kind": "decision",
            "to": "denis",
            "text": "which?",
            "answer_type": "text",
            "return_to": "ready",
            "deadline": "later",
            "on_timeout": "escalate",
        },
        actor="fixture",
    )
    if answered:
        turn.append(path, question.QUESTION, {"event": "answered", "verdict": "accept", "answer": "this one"}, actor="denis")
    return path


# 1. The appender


def test_a_legal_event_is_appended_and_folds(repo: Path) -> None:
    path = repo / turn.ITEMS / "itm-x.jsonl"

    folded = turn.append(path, backlog.ITEM, CREATED, actor="tester")

    assert folded.state == "ready"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_an_illegal_transition_leaves_the_log_byte_for_byte(repo: Path) -> None:
    path = seed_item(repo)
    before = path.read_bytes()

    with pytest.raises(LogError):
        turn.append(path, backlog.ITEM, {"event": "started"}, actor="tester")

    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".candidate").exists()


def test_a_missing_required_field_leaves_the_log_byte_for_byte(repo: Path) -> None:
    path = seed_item(repo)
    before = path.read_bytes()

    with pytest.raises(LogError):
        turn.append(path, backlog.ITEM, {"event": "claimed", "owner": "o"}, actor="tester")

    assert path.read_bytes() == before


def test_an_event_may_not_carry_its_own_identity(repo: Path) -> None:
    path = repo / turn.ITEMS / "itm-y.jsonl"

    with pytest.raises(turn.TurnError, match="event_id"):
        turn.append(path, backlog.ITEM, {**CREATED, "event_id": "mine"}, actor="tester")


def test_item_ids_are_generated_without_reading_anything() -> None:
    assert turn.new_item_id() != turn.new_item_id()
    assert turn.new_item_id().startswith("itm-")


# 2. Acquire and classify


def test_an_empty_backlog_plans(repo: Path, limits: Guardrails) -> None:
    executor = FakeExecutor(proposal=[CREATED])

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    assert len(list((repo / turn.ITEMS).glob("*.jsonl"))) == 1
    assert executor.calls[0]["goal"] == turn.DEFAULT_PLANNING_FRAME["goal"]


def test_a_ready_item_is_acted_on_and_only_one_of_them(repo: Path, limits: Guardrails) -> None:
    first, second = seed_item(repo), seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    take(repo, executor, limits)

    states = {path.stem: backlog.load(path).state for path in (first, second)}
    assert sorted(states.values()) == ["cancelled", "ready"]


def test_an_answered_question_unblocks_its_item_in_the_same_turn(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo, state="blocked")
    seed_question(repo, item.stem, answered=True)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "done with it"})

    take(repo, executor, limits)

    assert backlog.load(item).state == "cancelled"
    assert executor.calls, "the unblocked item should have been eligible in this same turn"


def test_an_open_question_leaves_its_item_ineligible(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo, state="blocked")
    seed_question(repo, item.stem, answered=False)
    # unstick-the-backlog: `blocked` no longer suppresses planning on its own (S1021) -- a genuinely
    # live claim, elsewhere, is what keeps this turn on the free `nothing-ready` path, so the
    # assertion below stays about the *blocked item*, not about `should_plan`'s own predicate
    # (covered separately in test_turn_cycle's should_plan unit tests).
    in_flight = seed_item(repo, state="ready")
    turn.append(
        in_flight,
        backlog.ITEM,
        {"event": "claimed", "owner": "o", "expires_at": "2099-01-01T00:00:00+00:00", "attempt": 1},
        actor="fixture",
    )
    executor = FakeExecutor()

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.NOTHING_READY
    assert backlog.load(item).state == "blocked"
    assert not executor.calls


def test_a_phase_argument_is_refused_before_anything_runs(repo: Path, limits: Guardrails) -> None:
    executor = FakeExecutor()

    with pytest.raises(turn.TurnError, match="derived from item state"):
        take(repo, executor, limits, phase="plan")

    assert not executor.calls


# 3. Nothing ready


def test_nothing_ready_costs_no_agent_and_writes_one_record(repo: Path, limits: Guardrails) -> None:
    seed_item(repo, state="blocked")
    seed_question(repo, "itm-absent", answered=False)
    # unstick-the-backlog: a `blocked` item alone no longer suppresses planning (S1021) -- a live
    # claim is what keeps this specific turn nothing-ready, so this test still exercises what it
    # names (no agent, one record) rather than accidentally re-testing `should_plan`.
    in_flight = seed_item(repo, state="ready")
    turn.append(
        in_flight,
        backlog.ITEM,
        {"event": "claimed", "owner": "o", "expires_at": "2099-01-01T00:00:00+00:00", "attempt": 1},
        actor="fixture",
    )
    executor = FakeExecutor()

    record = take(repo, executor, limits)

    assert not executor.calls
    assert record.outcome is Outcome.NOTHING_READY
    assert record.enforced_by is EnforcedBy.HARNESS
    assert len(list((repo / turn.RUNS).glob("*.json"))) == 1


# 4. The proposal channel


def test_two_events_are_refused_on_an_acting_turn(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    before = item.read_bytes()
    executor = FakeExecutor(proposal=[{"event": "cancelled", "reason": "a"}, {"event": "cancelled", "reason": "b"}])

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.FAILED
    assert b"cancelled" not in item.read_bytes()
    assert before in item.read_bytes()


def test_a_missing_proposal_is_a_failure_not_a_silence(repo: Path, limits: Guardrails) -> None:
    seed_item(repo)
    executor = FakeExecutor(proposal=None)

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.FAILED
    assert "wrote no proposal" in record.note


def test_an_unparseable_proposal_fails(repo: Path, limits: Guardrails) -> None:
    seed_item(repo)
    executor = FakeExecutor(raw="not json at all")

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.FAILED
    assert "not valid JSON" in record.note


def test_an_executor_failure_is_the_turns_failure(repo: Path, limits: Guardrails) -> None:
    seed_item(repo)
    executor = FakeExecutor(outcome=RunOutcome.FAILED)

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.FAILED
    assert record.enforced_by is EnforcedBy.HARNESS


# 5. Claim, act, record


def test_the_claim_is_committed_before_the_executor_runs(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    take(repo, executor, limits)

    assert f"claim({item.stem})" in executor.log_at_call[0]


def test_a_done_with_a_failing_gate_writes_no_done_event(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"})

    record = take(repo, executor, limits, test_command=FALSE_COMMAND)

    assert record.outcome is Outcome.FAILED
    assert backlog.load(item).state == "doing"
    assert "VERIFICATION FAILED" in record.note


def test_a_gate_rejection_reaches_the_item_and_the_next_turns_context(repo: Path, limits: Guardrails) -> None:
    """S1037/D030: the rejection must land on the item, not only the ledger's `TurnRecord`, and
    the next turn against the same item must inherit it through `context` while its `frame` stays
    byte-identical to the rejected attempt's — the two channels stay separate."""
    item = seed_item(repo)
    first = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"})

    take(repo, first, limits, test_command=FALSE_COMMAND)

    folded = backlog.load(item)
    assert folded.state == "doing"
    rejected = [r for r in folded.records if r["event"] == "gate_rejected"]
    assert len(rejected) == 1
    assert "VERIFICATION FAILED" in rejected[0]["report"]
    assert rejected[0]["attempt"] == 1
    # Committed in the same turn — not left dangling for a later commit to sweep up.
    assert f"{item.stem}" in "".join(git(repo, "show", "--stat", "HEAD"))

    # resume-gate-rejected-item / S236: `eligible()` admits the still-`doing` item directly --
    # no manual reclaim needed, and `attempt` must not move for a rejection ADR-0015 keeps within
    # the same attempt.
    second = FakeExecutor(proposal={"event": "cancelled", "reason": "done testing"})
    take(repo, second, limits)

    assert second.calls[0] == first.calls[0]  # frame byte-identical across the rejection
    assert second.contexts[0]["gate_rejection"]["report"] == rejected[0]["report"]
    assert [r["event"] for r in backlog.load(item).records].count("claimed") == 1



def test_a_gate_rejected_item_is_retried_without_waiting_out_its_lease(repo: Path, limits: Guardrails) -> None:
    """S236, the defect this change fixes: a rejection well inside its lease must be retryable on
    the very next turn, not only after `expires_at`. Before resume-gate-rejected-item, `eligible()`
    admitted only `ready`, so this second turn found nothing eligible, `should_plan` was suppressed
    by the still-`doing` item, and the turn recorded `nothing-ready` without ever calling the
    executor -- this test fails on that code and passes once `eligible()`/`take_turn` resume the
    item directly."""
    item = seed_item(repo)
    rejecting = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"})
    take(repo, rejecting, limits, test_command=FALSE_COMMAND)

    before = backlog.load(item)
    assert before.state == "doing"
    assert before.records[-1]["event"] == "gate_rejected"
    lease_before = backlog.lease(before)
    assert lease_before is not None

    succeeding = FakeExecutor(proposal={"event": "cancelled", "reason": "done testing"})
    record = take(repo, succeeding, limits)

    assert succeeding.calls, "a gate-rejected item inside its lease must be eligible on the next turn"
    assert record.outcome is Outcome.ADVANCED
    after = backlog.load(item)
    events = [r["event"] for r in after.records]
    assert events.count("claimed") == 1, "the resume must not append a second `claimed`"
    assert "reclaimed" not in events and "released" not in events
    only_claim = next(r for r in after.records if r["event"] == "claimed")
    claim_lease = {"owner": only_claim["owner"], "expires_at": only_claim["expires_at"], "attempt": only_claim["attempt"]}
    assert claim_lease == lease_before, "the one `claimed` record on the log must be unchanged by the resume"
    assert after.records[-1]["event"] == "cancelled"  # nothing but the new attempt's own event lands


def test_an_always_rejecting_item_still_poisons_within_max_attempts(repo: Path, limits: Guardrails) -> None:
    """The bound this change must not weaken: an item whose gate can never pass still reaches
    `poison`. The fast path added here never fires once a lease has actually expired -- so this
    walks the pre-existing `reclaim_expired` cycle (unstick-the-backlog / S1021), one simulated
    daily wake at a time, and must poison within `max_attempts` reclaim cycles exactly as it did
    before this change."""
    from datetime import UTC, datetime, timedelta

    item = seed_item(repo)
    always_rejects = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "t"})
    base = datetime(2026, 1, 1, tzinfo=UTC)

    for day in range(limits.max_attempts):
        take(repo, always_rejects, limits, test_command=FALSE_COMMAND, now=base + timedelta(days=day))
        folded = backlog.load(item)
        assert folded.state == "doing", f"day {day}: still retryable, not yet poisoned"

    take(repo, always_rejects, limits, test_command=FALSE_COMMAND, now=base + timedelta(days=limits.max_attempts))

    folded = backlog.load(item)
    assert folded.state == "poison"
    events = [r["event"] for r in folded.records]
    assert events[-2:] == ["failed", "poisoned"]
    claims = events.count("claimed")
    assert claims == limits.max_attempts, "each poison-bound cycle is one real claim, unaffected by the fast path"

def test_a_done_with_a_passing_gate_advances(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"})

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    assert record.enforced_by is EnforcedBy.AGENT
    assert backlog.load(item).state == "done"


def test_a_turns_spend_row_is_committed_not_merely_written(repo: Path, limits: Guardrails) -> None:
    """The receipt commit-the-spend-row-inside-the-turn exists for: a row on disk that a later,
    unrelated commit might sweep up is not evidence, and neither is `Path.exists()` (K signal
    S194 — an instrument reporting on its own execution rather than on its subject). The subject
    is `git show HEAD`: is the row actually part of the commit history, in the same commit as the
    run record it describes."""
    seed_item(repo)
    executor = FakeExecutor(
        proposal={"event": "done", "effects": ["none"], "verified_by": "tests"}, total_cost_usd=0.2583899
    )

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.ADVANCED

    # Same commit as the run record, not a later sweep: the run record's own path is always part
    # of this commit's diff (`_finish` always writes one), so finding both there together is the
    # atomicity claim, not just the row's presence somewhere in history.
    changed = git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert "ledger/spend.jsonl" in changed
    assert any(path.startswith("ledger/runs/") for path in changed)

    committed = git(repo, "show", "HEAD:ledger/spend.jsonl")
    rows = [json.loads(line) for line in committed.splitlines() if line.strip()]
    matching = [row for row in rows if row["run_id"] == record.run_id]
    assert len(matching) == 1
    assert matching[0]["total_cost_usd"] == pytest.approx(0.2583899)

    # And nothing is left behind uncommitted — the whole point of folding it into `_finish`'s own
    # `commit()` call rather than writing it out of band.
    assert not turn._git(repo, ["status", "--porcelain"], {}, check=False).stdout.strip()


def test_a_turn_that_spent_exactly_zero_still_commits_a_row(repo: Path, limits: Guardrails) -> None:
    """Zero cost is a real value (`runtime.spend.record`'s own docstring) — absence must not read
    as "this run never happened.\""""
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"}, total_cost_usd=0.0)

    record = take(repo, executor, limits)

    committed = git(repo, "show", "HEAD:ledger/spend.jsonl")
    rows = [json.loads(line) for line in committed.splitlines() if line.strip()]
    matching = [row for row in rows if row["run_id"] == record.run_id]
    assert len(matching) == 1
    assert matching[0]["total_cost_usd"] == 0.0


def test_a_planning_turn_that_created_nothing_still_commits_its_spend_row(repo: Path, limits: Guardrails) -> None:
    """A planning turn never claims an item, but it still runs an executor and still spends —
    the spend row must not be conditioned on there being an item to attach a commit to."""
    planner = FakeExecutor(proposal=[CREATED], total_cost_usd=0.0091)

    record = take(repo, planner, limits)

    assert record.outcome is Outcome.ADVANCED
    committed = git(repo, "show", "HEAD:ledger/spend.jsonl")
    rows = [json.loads(line) for line in committed.splitlines() if line.strip()]
    matching = [row for row in rows if row["run_id"] == record.run_id]
    assert len(matching) == 1
    assert matching[0]["total_cost_usd"] == pytest.approx(0.0091)


def test_a_spend_write_failure_does_not_cost_the_turn_its_run_record(
    repo: Path, limits: Guardrails, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Priority order: the ledger record must survive a spend-recording failure. Simulated by
    making the spend log's parent directory unwritable-in-effect: `spend.record` is monkeypatched
    to raise `OSError`, the same exception class `_finish` is written to catch."""
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"}, total_cost_usd=1.23)

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(turn.spend, "record", _raise)

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    assert "spend row not recorded" in record.note
    # The run record itself, and the item's own transition to `done`, both still committed.
    changed = git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert any(path.startswith("ledger/runs/") for path in changed)
    assert "ledger/spend.jsonl" not in changed
    assert not turn._git(repo, ["status", "--porcelain"], {}, check=False).stdout.strip()


def test_a_blocked_proposal_records_blocked_and_keeps_its_awaiting(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    awaiting = {
        "kind": "question",
        "ref": "q-2",
        "who": "denis",
        "since": "now",
        "return_to": "ready",
        "nudge_at": [],
        "deadline": "later",
        "on_timeout": "escalate",
    }
    executor = FakeExecutor(proposal={"event": "blocked", "awaiting": awaiting})

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.BLOCKED
    folded = backlog.load(item)
    assert folded.state == "blocked"
    assert backlog.awaiting(folded) == awaiting


def test_the_frame_carries_no_plumbing(repo: Path, limits: Guardrails) -> None:
    """D019's frame is the unit of falsification. A file path is not a claim that can be wrong."""
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    take(repo, executor, limits)

    assert set(executor.calls[0]) == set(FRAME)
    invocation = executor.invocations[0]
    assert invocation is not None
    assert invocation.skill == SKILL
    assert invocation.proposal_path is not None and item.stem not in str(invocation.proposal_path)


def test_the_agent_is_pointed_at_required_fields_before_writing(repo: Path, limits: Guardrails) -> None:
    """`teach-the-done-event-schema`'s reachability receipt: proof by construction through the
    real, unconditional `Invocation(...)` call site in `take_turn`, not a hand-built copy asserted
    in isolation. `test_the_vocabulary_table_promises_at_least_what_the_fold_requires`
    (`tests/protocol/test_backlog_fold.py`) is the content half; this is the wiring half."""
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    take(repo, executor, limits)

    invocation = executor.invocations[0]
    assert invocation is not None
    assert invocation.vocabulary == backlog.VOCABULARY_SPEC
    rendered = invocation.render()
    assert "check it before you" in rendered
    assert str(backlog.VOCABULARY_SPEC) in rendered
    # The reminder points; it never restates. If a required field name shows up here, the
    # vocabulary has a second, drift-prone definition.
    for field in ("effects", "verified_by", "awaiting"):
        assert field not in rendered


def test_the_record_names_the_item(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    record = take(repo, executor, limits)

    assert item.stem in record.note


# 6. Planning


def test_a_planning_turn_writes_items_and_does_not_act_on_them(repo: Path, limits: Guardrails) -> None:
    executor = FakeExecutor(proposal=[CREATED, CREATED])

    record = take(repo, executor, limits)

    written = sorted((repo / turn.ITEMS).glob("*.jsonl"))
    assert len(written) == 2
    assert {backlog.load(path).state for path in written} == {"ready"}
    assert record.outcome is Outcome.ADVANCED
    assert len(executor.calls) == 1


# 7. Concurrency posture


def test_a_second_turn_on_a_locked_tree_does_not_start(repo: Path, limits: Guardrails) -> None:
    from yosefactory.runtime.supervise import LockBusy

    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    with single_flight(repo / turn.LOCK), pytest.raises(LockBusy):
        take(repo, executor, limits)

    assert not executor.calls


def test_cross_machine_without_the_cas_push_is_refused(repo: Path, limits: Guardrails) -> None:
    executor = FakeExecutor()

    with pytest.raises(turn.TurnError, match="compare-and-swap"):
        take(repo, executor, limits, cross_machine=True)

    assert not executor.calls


# 8. The skill


def test_the_skill_stays_short() -> None:
    words = len(Path("workflows/turn-skill.md").read_text(encoding="utf-8").split())

    assert words < 120, "S098: a 1,500-word prompt performed worse than a 103-word one"


def test_the_skill_still_teaches_the_commit_precondition() -> None:
    """Regression only: guards the instruction's presence, not that an agent obeys it. The
    harness's own `Co-Authored-By: Claude` line died silently this same way once — a prose
    convention nothing asserted (`orchestration.md`, "Commit attribution")."""
    text = Path("workflows/turn-skill.md").read_text(encoding="utf-8")

    assert "commit" in text.lower()
    assert "git add -a" in text.lower(), "the forbidden blanket-stage form must be named, not implied"


# 9. Acceptance


def test_two_turns_share_nothing_but_the_repository(repo: Path, limits: Guardrails) -> None:
    planner = FakeExecutor(proposal=[CREATED])
    first = take(repo, planner, limits)

    assert first.outcome is Outcome.ADVANCED
    assert not turn._git(repo, ["status", "--porcelain"], {}, check=False).stdout.strip()

    actor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})
    second = take(repo, actor, limits)

    assert second.outcome is Outcome.ADVANCED
    planned = next(iter((repo / turn.ITEMS).glob("*.jsonl")))
    assert backlog.load(planned).state == "done"
    assert actor.calls[0]["goal"] == FRAME["goal"], "turn two read the frame turn one committed"
    assert len(list((repo / turn.RUNS).glob("*.json"))) == 2


def test_the_mapping_is_total_over_the_executor_vocabulary() -> None:
    """A new vendor stop must fail here rather than silently record a run with no reason."""
    assert set(turn._RUN_LEVEL_KIND) == set(RunOutcome)


def test_a_run_level_stop_is_recorded_as_its_own_reason() -> None:
    """The distinction rule 3 protects: starvation reaches the record typed, not narrated."""
    for stop, expected in (
        # Only the protocol vocabulary has these. The executor's run-level stops carry no typed
        # kind of their own, which is exactly why the recordable set is a union and not a mirror.
        (RunOutcome.BUDGET_EXHAUSTED, ProtocolFailureKind.BUDGET_EXHAUSTED),
        (RunOutcome.TURN_LIMIT, ProtocolFailureKind.TURN_LIMIT),
        (RunOutcome.CANCELLED, ProtocolFailureKind.CANCELLED),
    ):
        result = RunResult(
            outcome=stop, usage=Usage(), transcript_path=Path("t"), exit_code=0, dirty=False, failure_kind=None
        )
        assert turn.failure_kind_of(result) is expected


# 10. Commit attribution


def trailers(repo: Path, *, rev: str = "HEAD") -> str:
    return git(repo, "log", "-1", "--format=%(trailers)", rev)


def test_a_platform_commit_carries_both_trailers(repo: Path, limits: Guardrails) -> None:
    executor = FakeExecutor(proposal=[CREATED])

    record = take(repo, executor, limits)

    body = trailers(repo)
    assert f"Co-Authored-By: {turn.PLATFORM_CO_AUTHOR}" in body
    assert f"{turn.RUN_TRAILER_KEY}: {record.run_id}" in body


def test_the_run_trailer_names_the_committed_record(repo: Path, limits: Guardrails) -> None:
    executor = FakeExecutor(proposal=[CREATED])

    record = take(repo, executor, limits)

    assert f"{turn.RUN_TRAILER_KEY}: {record.run_id}" in trailers(repo)
    matches = list((repo / turn.RUNS).glob(f"*-{record.run_id}.json"))
    assert len(matches) == 1
    assert json.loads(matches[0].read_text(encoding="utf-8"))["run_id"] == record.run_id


def test_an_existing_co_author_is_kept_alongside_the_platforms(repo: Path) -> None:
    item_path = repo / "note.txt"
    item_path.write_text("x\n", encoding="utf-8")
    message = "hand-authored\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"

    turn.commit(repo, [item_path], message, run_id=turn.new_run_id())

    body = trailers(repo)
    assert "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>" in body
    assert f"Co-Authored-By: {turn.PLATFORM_CO_AUTHOR}" in body
    log = git(repo, "log", "-1", "--format=%s")
    assert log == "hand-authored"


def test_the_message_body_is_unchanged(repo: Path) -> None:
    item_path = repo / "note.txt"
    item_path.write_text("x\n", encoding="utf-8")
    run_id = turn.new_run_id()

    turn.commit(repo, [item_path], "subject line\n\na body paragraph.", run_id=run_id)

    full = git(repo, "log", "-1", "--format=%B")
    assert full.startswith("subject line\n\na body paragraph.")


def test_the_platform_identity_is_byte_identical_across_runs(repo: Path) -> None:
    first_file = repo / "a.txt"
    first_file.write_text("a\n", encoding="utf-8")
    turn.commit(repo, [first_file], "first", run_id=turn.new_run_id())

    second_file = repo / "b.txt"
    second_file.write_text("b\n", encoding="utf-8")
    turn.commit(repo, [second_file], "second", run_id=turn.new_run_id())

    first_trailer = [line for line in trailers(repo, rev="HEAD~1").splitlines() if line.startswith("Co-Authored-By: yosefactory")]
    second_trailer = [line for line in trailers(repo, rev="HEAD").splitlines() if line.startswith("Co-Authored-By: yosefactory")]
    assert first_trailer == second_trailer
    assert len(first_trailer) == 1


def test_a_refused_commit_leaves_nothing_staged(repo: Path) -> None:
    """No change to commit is a real git refusal — the same path a hook rejection takes."""
    unchanged = repo / "seed.txt"

    with pytest.raises(turn.TurnError, match="commit refused"):
        turn.commit(repo, [unchanged], "no-op", run_id=turn.new_run_id())

    assert not turn._git(repo, ["diff", "--cached", "--name-only"], {}, check=False).stdout.strip()


def test_trailers_extend_an_existing_block_without_duplicating_it(repo: Path) -> None:
    item_path = repo / "note.txt"
    item_path.write_text("x\n", encoding="utf-8")
    run_id = turn.new_run_id()
    message = "subject\n\nSigned-off-by: someone <s@example.invalid>"

    turn.commit(repo, [item_path], message, run_id=run_id)

    full = git(repo, "log", "-1", "--format=%B")
    assert full.count("\n\n") == 1, "one trailer block, not a second one appended after it"
    assert "Signed-off-by: someone" in full


# 10a. Workspace delivery — the platform commits the workspace's own boundary commit, not just the queue


def workspace_head(workspace: Path) -> str:
    return git(workspace, "rev-parse", "HEAD")


def checkpoint(workspace: Path, name: str, message: str) -> None:
    """One of the agent's own commits, made with plain git — the platform never sees this happen."""
    path = workspace / name
    path.write_text(f"{name}\n", encoding="utf-8")
    git(workspace, "add", name)
    git(workspace, "commit", "-q", "-m", message)


class CommittingExecutor(FakeExecutor):
    """A `FakeExecutor` that also makes real workspace commits during its own call.

    `_deliver_workspace` only amends a commit made *during this turn's executor call* — a checkpoint
    made before the turn starts is not this turn's own work and must not be touched. Making the
    checkpoints from inside `__call__`, exactly where a real agent would, is the difference between
    testing that and accidentally testing something else.
    """

    def __init__(self, checkpoints: list[tuple[str, str]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.checkpoints = checkpoints

    def __call__(self, frame: Mapping[str, Any], workspace: Path, limits: Guardrails, **kwargs: Any) -> RunResult:
        for name, message in self.checkpoints:
            checkpoint(workspace, name, message)
        return super().__call__(frame, workspace, limits, **kwargs)


def test_the_boundary_commit_is_amended_with_both_trailers(repo: Path, workspace: Path, limits: Guardrails) -> None:
    seed_item(repo)
    original_sha = workspace_head(workspace)
    executor = CommittingExecutor(
        [("work.txt", "agent's own checkpoint")],
        proposal={"event": "done", "effects": ["work.txt"], "verified_by": "tests"},
    )

    record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    delivered_sha = workspace_head(workspace)
    assert delivered_sha != original_sha, "the amend produces a new commit object"
    assert record.workspace_commit == delivered_sha
    body = trailers(workspace)
    assert f"Co-Authored-By: {turn.PLATFORM_CO_AUTHOR}" in body
    assert f"{turn.RUN_TRAILER_KEY}: {record.run_id}" in body
    assert git(workspace, "log", "-1", "--format=%s") == "agent's own checkpoint"


def test_only_the_boundary_commit_is_amended_earlier_checkpoints_survive(
    repo: Path, workspace: Path, limits: Guardrails
) -> None:
    seed_item(repo)
    executor = CommittingExecutor(
        [("first.txt", "first checkpoint"), ("second.txt", "second checkpoint")],
        proposal={"event": "done", "effects": ["first.txt", "second.txt"], "verified_by": "tests"},
    )

    record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    delivered = workspace_head(workspace)
    first_sha = git(workspace, "rev-parse", f"{delivered}~1")
    assert git(workspace, "log", "-1", "--format=%s", first_sha) == "first checkpoint"
    assert "Yosefactory-Run" not in trailers(workspace, rev=first_sha)
    assert f"{turn.RUN_TRAILER_KEY}: {record.run_id}" in trailers(workspace)


def test_no_workspace_commit_delivers_nothing(repo: Path, workspace: Path, limits: Guardrails) -> None:
    seed_item(repo)
    original_sha = workspace_head(workspace)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"})

    record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    assert record.workspace_commit == ""
    assert workspace_head(workspace) == original_sha


def test_delivery_does_not_re_run_the_workspaces_own_hooks(repo: Path, workspace: Path, limits: Guardrails) -> None:
    """Passes the first `git commit` (the checkpoint) once, then rejects any further invocation —
    so the amend can only succeed by not asking the hook a second time, exactly the property under
    test rather than a hook that would also have blocked the checkpoint itself."""
    hook_path = workspace / ".git" / "hooks" / "commit-msg"
    hook_path.write_text('#!/bin/sh\nmarker="$(dirname "$0")/.fired"\n[ -f "$marker" ] && exit 1\ntouch "$marker"\n', encoding="utf-8")
    hook_path.chmod(0o755)
    seed_item(repo)
    executor = CommittingExecutor(
        [("work.txt", "agent's own checkpoint")],
        proposal={"event": "done", "effects": ["work.txt"], "verified_by": "tests"},
    )

    record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED, record.note
    assert f"{turn.RUN_TRAILER_KEY}: {record.run_id}" in trailers(workspace)


def test_a_typed_executor_kind_survives_the_boundary() -> None:
    result = RunResult(
        outcome=RunOutcome.FAILED,
        usage=Usage(),
        transcript_path=Path("t"),
        exit_code=1,
        dirty=False,
        failure_kind=FailureKind.RATE_LIMIT,
    )

    assert turn.failure_kind_of(result) is ProtocolFailureKind.RATE_LIMIT


def test_a_run_that_did_not_fail_carries_no_reason() -> None:
    """A record rejects a reason on any outcome but `failed`, so the mapping may not invent one."""
    for outcome in (RunOutcome.SUCCESS, RunOutcome.NEEDS_APPROVAL, RunOutcome.REFUSED):
        result = RunResult(
            outcome=outcome, usage=Usage(), transcript_path=Path("t"), exit_code=0, dirty=False, failure_kind=None
        )
        assert turn.failure_kind_of(result) is None


def test_a_starved_run_writes_a_record_that_says_so(repo: Path, limits: Guardrails) -> None:
    """End to end: a budget stop lands in the stream as `budget_exhausted`, not as free text."""
    seed_item(repo)
    record = take(repo, FakeExecutor(outcome=RunOutcome.BUDGET_EXHAUSTED, kind=None), limits)

    assert record.outcome is Outcome.FAILED
    assert record.failure_kind is ProtocolFailureKind.BUDGET_EXHAUSTED
    assert starved(record.failure_kind) is True


def test_a_denied_approval_is_recorded_as_blocked_not_failed(repo: Path, limits: Guardrails) -> None:
    """The live defect: every non-success ending used to narrow to `failed`, so a run stopped by a
    permission denial read as broken. It is a wait, and something arriving can clear it."""
    seed_item(repo)
    record = take(repo, FakeExecutor(outcome=RunOutcome.NEEDS_APPROVAL), limits)

    assert record.outcome is Outcome.BLOCKED
    assert record.blocked_kind is BlockedKind.NEEDS_APPROVAL
    assert record.failure_kind is None
    assert resumable(record.blocked_kind) is True


def test_a_refusal_is_recorded_as_blocked_and_not_resumable(repo: Path, limits: Guardrails) -> None:
    """Also blocked, and distinguishably not a wait: nothing arrives that changes a refusal."""
    seed_item(repo)
    record = take(repo, FakeExecutor(outcome=RunOutcome.REFUSED), limits)

    assert record.outcome is Outcome.BLOCKED
    assert record.blocked_kind is BlockedKind.REFUSED
    assert resumable(record.blocked_kind) is False


def test_a_denied_approval_raises_a_question_the_item_can_be_found_from(repo: Path, limits: Guardrails) -> None:
    """The live defect this closes: a denial used to leave the item `doing` — neither `ready` nor
    truly `blocked` — and no later turn ever revisited it. It must now be `blocked` on a real question."""
    item_path = seed_item(repo)
    record = take(repo, FakeExecutor(outcome=RunOutcome.NEEDS_APPROVAL), limits)

    assert record.blocked_kind is BlockedKind.NEEDS_APPROVAL
    item = backlog.load(item_path)
    assert item.state == "blocked"
    awaiting = backlog.awaiting(item)
    assert awaiting is not None
    assert awaiting["kind"] == "question"

    asked_path = repo / turn.QUESTIONS / f"{awaiting['ref']}.jsonl"
    assert asked_path.exists()
    folded = question.load(asked_path)
    asked = question.asked(folded)
    assert asked["item"] == item_path.stem
    assert asked["return_to"] == "doing"
    assert asked["on_timeout"] == "default:no"
    assert asked["deadline"]


def test_the_raised_question_commits_with_the_platform_trailer(repo: Path, limits: Guardrails) -> None:
    seed_item(repo)
    take(repo, FakeExecutor(outcome=RunOutcome.NEEDS_APPROVAL), limits)

    body = git(repo, "log", "-1", "--format=%B")
    assert "Yosefactory-Run:" in body


def test_a_denied_approval_during_planning_writes_no_question(repo: Path, limits: Guardrails) -> None:
    """No item is claimed during planning, so there is nothing to suspend a question against — the
    same ledger-only ending `refused` always gets."""
    record = take(repo, FakeExecutor(outcome=RunOutcome.NEEDS_APPROVAL), limits)

    assert record.blocked_kind is BlockedKind.NEEDS_APPROVAL
    assert list((repo / turn.QUESTIONS).glob("*.jsonl")) == []


def test_a_refusal_still_writes_no_question(repo: Path, limits: Guardrails) -> None:
    """`refused` is a dead end by design (D019); nothing should be raised for it."""
    item_path = seed_item(repo)
    take(repo, FakeExecutor(outcome=RunOutcome.REFUSED), limits)

    assert backlog.load(item_path).state == "doing"
    assert list((repo / turn.QUESTIONS).glob("*.jsonl")) == []


def test_answering_the_raised_question_unblocks_the_item_next_turn(repo: Path, limits: Guardrails) -> None:
    """`apply_answers` needed no change — it already resolves `outcome()` and reads `return_to`. This
    is its first real feed for this path."""
    item_path = seed_item(repo)
    take(repo, FakeExecutor(outcome=RunOutcome.NEEDS_APPROVAL), limits)
    awaiting = backlog.awaiting(backlog.load(item_path))
    assert awaiting is not None
    asked_path = repo / turn.QUESTIONS / f"{awaiting['ref']}.jsonl"

    turn.append(asked_path, question.QUESTION, {"event": "answered", "verdict": "accept", "answer": "yes"}, actor="denis")
    moved = turn.apply_answers(repo, actor="tester")

    assert moved == [item_path.stem]
    folded = backlog.load(item_path)
    assert folded.state == "doing"

    # S1038/D030: the answer's text landed on the item itself, not only a pointer to the question.
    # `return_to` here is `doing`, not `ready` (`NEEDS_APPROVAL`'s own block), so the item is not
    # yet `eligible()` again -- reclaiming it to exercise a next turn is covered by
    # `test_a_gate_rejection_reaches_the_item_and_the_next_turns_context` above, which does that.
    unblocked = next(r for r in folded.records if r["event"] == "unblocked")
    assert unblocked["resolution"]["answer"] == "yes"
    assert backlog.context(folded) == {"answer": "yes"}


def test_the_note_no_longer_restates_the_reason(repo: Path, limits: Guardrails) -> None:
    """The workaround that carried the kind as text is retired; the typed field is its only home."""
    seed_item(repo)
    record = take(repo, FakeExecutor(outcome=RunOutcome.FAILED, kind=FailureKind.RATE_LIMIT), limits)

    assert record.failure_kind is ProtocolFailureKind.RATE_LIMIT
    assert "rate_limit" not in record.note
    assert "no kind" not in record.note


def test_a_starved_record_round_trips_through_the_stream(repo: Path, limits: Guardrails) -> None:
    """The reason must survive being written and read back, or the detector never sees it."""
    seed_item(repo)
    take(repo, FakeExecutor(outcome=RunOutcome.BUDGET_EXHAUSTED, kind=None), limits)

    window = read_window(repo / turn.RUNS, 5)

    assert [position.record.failure_kind for position in window if position.record] == [
        ProtocolFailureKind.BUDGET_EXHAUSTED
    ]


# 10. Places — queue and workspace as separate repositories


def test_places_local_uses_one_lock_for_both_roles(repo: Path) -> None:
    places = turn.Places.local(repo)

    assert places.queue == repo
    assert places.workspace == repo
    assert places.queue_lock == places.workspace_lock


def test_a_foreign_workspace_gets_no_queue_bookkeeping(repo: Path, workspace: Path, limits: Guardrails) -> None:
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})

    record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    assert executor.calls[0]["goal"] == FRAME["goal"]
    # The turn's own bookkeeping — items, questions, ledger — lands only in the queue.
    assert next(iter((repo / turn.ITEMS).glob("*.jsonl")), None) is not None
    assert list((repo / turn.RUNS).glob("*.json"))
    # None of it leaks into the workspace the agent was actually pointed at.
    assert not (workspace / turn.ITEMS).exists()
    assert not (workspace / turn.QUESTIONS).exists()
    assert not (workspace / "ledger").exists()


def test_the_agent_runs_with_the_workspace_as_its_cwd(repo: Path, workspace: Path, limits: Guardrails) -> None:
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    take_split(repo, workspace, executor, limits)

    assert executor.calls[0] is not None  # the call happened
    assert executor.workspaces[0] == workspace


def test_a_busy_workspace_lock_blocks_a_turn_before_the_agent_runs(repo: Path, workspace: Path, limits: Guardrails) -> None:
    from yosefactory.runtime.supervise import LockBusy

    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    with single_flight(workspace / turn.LOCK), pytest.raises(LockBusy):
        take_split(repo, workspace, executor, limits)

    assert not executor.calls, "the queue lock let picking happen, but the workspace lock refused the run"


def test_two_different_queues_targeting_one_workspace_still_serialize(
    repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails
) -> None:
    """The keying is by workspace identity, not by which queue dispatched the turn (S073's shape)."""
    from yosefactory.runtime.supervise import LockBusy

    other_queue = tmp_path / "other-queue"
    (other_queue / turn.ITEMS).mkdir(parents=True)
    (other_queue / turn.QUESTIONS).mkdir(parents=True)
    git(other_queue, "init", "-q")
    git(other_queue, "config", "user.email", "t@example.invalid")
    git(other_queue, "config", "user.name", "T")
    (other_queue / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(other_queue, "add", "seed.txt")
    git(other_queue, "commit", "-q", "-m", "seed")
    seed_item(other_queue)

    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "cancelled", "reason": "enough"})

    with single_flight(workspace / turn.LOCK), pytest.raises(LockBusy):
        take_split(other_queue, workspace, executor, limits)

    assert not executor.calls


# 11. Publication — D022


def test_an_advanced_turn_publishes_workspace_before_queue(
    repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_remote = bare_remote(tmp_path, "queue-remote")
    workspace_remote = bare_remote(tmp_path, "workspace-remote")
    set_origin(repo, queue_remote)
    set_origin(workspace, workspace_remote)
    seed_item(repo)

    calls: list[Path] = []
    original = turn.push_repo

    def spy(target: Path) -> turn.PublishResult:
        calls.append(target)
        return original(target)

    monkeypatch.setattr(turn, "push_repo", spy)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})

    record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    assert calls == [workspace, repo], "the workspace publishes before the queue"
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(queue_remote, "rev-parse", branch) == git(repo, "rev-parse", branch)
    branch = git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(workspace_remote, "rev-parse", branch) == git(workspace, "rev-parse", branch)


def test_no_remote_configured_publishes_nothing_and_warns_nothing(repo: Path, workspace: Path, limits: Guardrails) -> None:
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED


def test_a_rejected_push_warns_and_does_not_fail_the_turn(
    repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails
) -> None:
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    workspace_remote = bare_remote(tmp_path, "workspace-remote")
    queue_remote = diverged_remote(tmp_path, "queue-remote", branch)
    set_origin(workspace, workspace_remote)
    set_origin(repo, queue_remote)
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})

    with pytest.warns(turn.PublicationFailed, match="rejected"):
        record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED, "a publication failure never touches the turn's own record"
    workspace_branch = git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(workspace_remote, "rev-parse", workspace_branch) == git(workspace, "rev-parse", workspace_branch), (
        "the workspace push still succeeded even though the queue push was rejected"
    )


def test_a_failed_turn_publishes_nothing(repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails) -> None:
    queue_remote = bare_remote(tmp_path, "queue-remote")
    workspace_remote = bare_remote(tmp_path, "workspace-remote")
    set_origin(repo, queue_remote)
    set_origin(workspace, workspace_remote)
    seed_item(repo)
    executor = FakeExecutor(outcome=RunOutcome.FAILED, kind=FailureKind.CRASH)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.FAILED
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(queue_remote, "branch", "--list", branch) == ""


def test_a_blocked_turn_publishes_nothing(repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails) -> None:
    queue_remote = bare_remote(tmp_path, "queue-remote")
    workspace_remote = bare_remote(tmp_path, "workspace-remote")
    set_origin(repo, queue_remote)
    set_origin(workspace, workspace_remote)
    seed_item(repo)
    awaiting = {
        "kind": "question",
        "ref": "q-2",
        "who": "denis",
        "since": "now",
        "return_to": "ready",
        "nudge_at": [],
        "deadline": "later",
        "on_timeout": "escalate",
    }
    executor = FakeExecutor(proposal={"event": "blocked", "awaiting": awaiting})

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.BLOCKED
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(queue_remote, "branch", "--list", branch) == ""


# 12. Declining publication per place -- `decline-publication-per-place`


def test_a_declined_workspace_is_never_pushed(
    repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`push_repo` must never be called for a declined place -- checked by spy, not by outcome."""
    queue_remote = bare_remote(tmp_path, "queue-remote")
    workspace_remote = bare_remote(tmp_path, "workspace-remote")
    set_origin(repo, queue_remote)
    set_origin(workspace, workspace_remote)
    seed_item(repo)

    calls: list[Path] = []
    original = turn.push_repo

    def spy(target: Path) -> turn.PublishResult:
        calls.append(target)
        return original(target)

    monkeypatch.setattr(turn, "push_repo", spy)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})

    record = take_split(repo, workspace, executor, limits, publish_workspace=False)

    assert record.outcome is Outcome.ADVANCED
    assert calls == [repo], "push_repo was never invoked for the declined workspace"
    branch = git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(workspace_remote, "branch", "--list", branch) == "", "nothing reached the workspace remote"
    # The queue, not declined, still published normally.
    assert git(queue_remote, "rev-parse", branch) == git(repo, "rev-parse", branch)


def test_declined_is_not_conflated_with_skipped_even_with_a_real_remote(
    repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails
) -> None:
    """A declined place with a real, reachable origin must still report `declined`, not `skipped`.

    Proves the check happens before `push_repo` runs, not by classifying `push_repo`'s own result:
    the remote below is real and reachable, so a `skipped` result would only occur if the decline
    check were bypassed and `push_repo` fell through to "no remote" some other way -- it should
    never be consulted at all.
    """
    queue_remote = bare_remote(tmp_path, "queue-remote")
    workspace_remote = bare_remote(tmp_path, "workspace-remote")
    set_origin(repo, queue_remote)
    set_origin(workspace, workspace_remote)
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})

    places = turn.Places(
        queue=repo,
        ledger=repo / turn.RUNS,
        queue_lock=repo / turn.LOCK,
        workspace=workspace,
        workspace_lock=workspace / turn.LOCK,
        transcripts=repo / turn.RUNS,
        publish_workspace=False,
    )
    record = turn.take_turn(
        places, executor, limits=limits, owner="tester", skill=SKILL, proposal_dir=repo.parent, test_command=TRUE_COMMAND
    )
    assert record.outcome is Outcome.ADVANCED

    result = turn.publish(places, record)
    assert result is not None
    workspace_result, queue_result = result
    assert workspace_result.status == "declined"
    assert queue_result.status == "pushed"


def test_an_unstated_publish_choice_publishes_both_places_exactly_as_before(
    repo: Path, workspace: Path, tmp_path: Path, limits: Guardrails
) -> None:
    """Decision 2: a caller supplying no opinion behaves exactly as every turn did before this field."""
    queue_remote = bare_remote(tmp_path, "queue-remote")
    workspace_remote = bare_remote(tmp_path, "workspace-remote")
    set_origin(repo, queue_remote)
    set_origin(workspace, workspace_remote)
    seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["a commit"], "verified_by": "tests"})

    record = take_split(repo, workspace, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(queue_remote, "rev-parse", branch) == git(repo, "rev-parse", branch)
    branch = git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
    assert git(workspace_remote, "rev-parse", branch) == git(workspace, "rev-parse", branch)


# ---------------------------------------------------------------------------
# 13. unstick-the-backlog / S1021 -- should_plan narrowed, leases reclaimed, exhaustion poisoned
# ---------------------------------------------------------------------------


def _seed_stuck_item(repo: Path, *, event: str, **payload: Any) -> Path:
    """A `claimed`/`doing` item pushed straight into a terminal-adjacent dead end -- `failed`,
    `falsified`, or `needs_split` -- with no route back to `ready` in the transition table."""
    path = repo / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(path, backlog.ITEM, CREATED, actor="fixture")
    turn.append(path, backlog.ITEM, {"event": "claimed", "owner": "o", "expires_at": "later", "attempt": 1}, actor="fixture")
    turn.append(path, backlog.ITEM, {"event": "started"}, actor="fixture")
    turn.append(path, backlog.ITEM, {"event": event, **payload}, actor="fixture")
    return path


def test_a_single_failed_item_does_not_freeze_planning_forever(repo: Path, limits: Guardrails) -> None:
    """The regression test S1021 asks for directly: a backlog whose only item is stuck in a
    non-terminal, non-eligible state must not forbid all future work. Before unstick-the-backlog,
    `should_plan` treated `failed` as "in flight" and this turn would have reported `nothing-ready`
    forever, for $0, exactly as the signal describes."""
    item = _seed_stuck_item(repo, event="failed", reason="boom", attempt=1, retryable=True)

    executor = FakeExecutor(proposal=[{"event": "created", "loop": "l", "frame": FRAME}])
    record = take(repo, executor, limits)

    assert executor.calls, "a stuck item must not forbid planning -- the turn should have plans instead of nothing-ready"
    assert record.outcome is Outcome.ADVANCED
    assert backlog.load(item).state == "failed"  # the stuck item itself is untouched


def test_a_backlog_of_only_falsified_and_needs_split_items_still_plans(repo: Path, limits: Guardrails) -> None:
    """The same regression, for the two states with no route back at all -- `falsified` and
    `needs_split`, neither of which this change gives a new transition to."""
    _seed_stuck_item(repo, event="falsified", by="disproven", successor="itm-successor")
    _seed_stuck_item(repo, event="needs_split", children=["itm-a", "itm-b"])

    executor = FakeExecutor(proposal=[{"event": "created", "loop": "l", "frame": FRAME}])
    record = take(repo, executor, limits)

    assert executor.calls
    assert record.outcome is Outcome.ADVANCED


def test_should_plan_is_suppressed_only_by_a_live_claim() -> None:
    """Unit coverage for the predicate itself, independent of a full turn."""
    from types import SimpleNamespace

    stuck_states = ["failed", "falsified", "needs_split", "blocked", "snoozed"]
    for state in stuck_states:
        assert turn.should_plan([SimpleNamespace(state=state)]), f"{state!r} must not suppress planning"
    for state in ("claimed", "doing"):
        assert not turn.should_plan([SimpleNamespace(state=state)]), f"{state!r} must suppress planning"
    assert turn.should_plan([SimpleNamespace(state=s) for s in stuck_states])  # mixed, still plans
    assert not turn.should_plan([SimpleNamespace(state="ready"), SimpleNamespace(state="doing")])


def test_an_expired_lease_is_reclaimed_and_may_be_reclaimed_in_the_same_turn(repo: Path, limits: Guardrails) -> None:
    """The reclamation path, direct: an item claimed by a turn that never finished -- its lease's
    `expires_at` is in the past and no further event was ever appended, exactly what a crash or an
    OOM kill leaves behind."""
    from datetime import UTC, datetime

    item = repo / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(item, backlog.ITEM, CREATED, actor="fixture")
    turn.append(
        item,
        backlog.ITEM,
        {"event": "claimed", "owner": "dead-turn", "expires_at": "2026-01-01T00:00:00+00:00", "attempt": 1},
        actor="fixture",
    )
    turn.append(item, backlog.ITEM, {"event": "started"}, actor="fixture")

    executor = FakeExecutor(proposal={"event": "priority_set", "priority": 5})
    record = take(repo, executor, limits, now=datetime(2026, 1, 2, tzinfo=UTC))

    assert executor.calls, "the reclaimed item should have been eligible again in this same turn"
    assert record.outcome is Outcome.ADVANCED
    folded = backlog.load(item)
    assert folded.state == "doing"
    assert backlog.lease(folded)["attempt"] == 2  # claimed again, attempt incremented past the dead lease
    events = [record["event"] for record in folded.records]
    assert events.count("reclaimed") == 1
    assert events.count("claimed") == 2


def test_a_lease_that_keeps_expiring_is_poisoned_not_reclaimed_forever(repo: Path, limits: Guardrails) -> None:
    """Exhaustion path: an item whose lease has expired for the `max_attempts`-th time is poisoned
    instead of reclaimed -- a crash-looping item stops consuming turns rather than retrying forever."""
    from datetime import UTC, datetime

    item = repo / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(item, backlog.ITEM, CREATED, actor="fixture")
    turn.append(
        item,
        backlog.ITEM,
        {"event": "claimed", "owner": "dead-turn", "expires_at": "2026-01-01T00:00:00+00:00", "attempt": limits.max_attempts},
        actor="fixture",
    )
    turn.append(item, backlog.ITEM, {"event": "started"}, actor="fixture")

    # nothing else is ready or claimed once the poison sweep runs, so this turn plans -- give it
    # something legal to propose rather than asserting it is never called.
    executor = FakeExecutor(proposal=[{"event": "created", "loop": "l", "frame": FRAME}])
    take(repo, executor, limits, now=datetime(2026, 1, 2, tzinfo=UTC))

    folded = backlog.load(item)
    assert folded.state == "poison"
    events = [record["event"] for record in folded.records]
    assert "reclaimed" not in events
    assert events[-2:] == ["failed", "poisoned"]


def test_a_non_retryable_failure_poisons_immediately(repo: Path, limits: Guardrails) -> None:
    """`retryable: false` poisons on the first failure, regardless of `attempt` -- the agent's own
    judgment that retrying is pointless is trusted once rather than re-litigated `max_attempts` times."""
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "failed", "reason": "unrecoverable", "attempt": 1, "retryable": False})

    take(repo, executor, limits)

    assert backlog.load(item).state == "poison"


def test_a_retryable_failure_under_the_cap_is_not_poisoned(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "failed", "reason": "transient", "attempt": 1, "retryable": True})

    take(repo, executor, limits)

    assert backlog.load(item).state == "failed"  # not poisoned -- under the cap and retryable


def test_a_sweeps_writes_are_committed_with_the_turn_and_do_not_dirty_the_tree(repo: Path, limits: Guardrails) -> None:
    """The commit-scoping fix, found wiring the reclaim sweep: an item the sweep moves, other than
    the one the turn goes on to act on, must land in a commit -- not sit uncommitted in the tree,
    where `Places.local` (queue == workspace) would misread it as the agent's own dirty work."""
    from datetime import UTC, datetime

    swept = repo / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(swept, backlog.ITEM, CREATED, actor="fixture")
    turn.append(
        swept,
        backlog.ITEM,
        {"event": "claimed", "owner": "dead-turn", "expires_at": "2026-01-01T00:00:00+00:00", "attempt": 1},
        actor="fixture",
    )
    turn.append(swept, backlog.ITEM, {"event": "started"}, actor="fixture")
    target = seed_item(repo)  # a second, ready item -- this is the one the turn actually acts on
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed both items")

    executor = FakeExecutor(proposal={"event": "priority_set", "priority": 5})
    take(repo, executor, limits, now=datetime(2026, 1, 2, tzinfo=UTC))

    # The tree is clean at the end -- nothing the sweep wrote was left uncommitted for a fresh
    # clone to miss.
    assert git(repo, "status", "--porcelain") == ""
    # And it is not merely present on disk: it is reachable from `HEAD` by walking that file's own
    # history, i.e. it was actually staged and committed, not written and forgotten
    # (`apply_answers`'s own pre-existing defect, before this change fixed it).
    swept_relative = str(swept.relative_to(repo))
    assert "reclaimed" in git(repo, "log", "-p", "--follow", "--", swept_relative)
    # Whichever of the two `pick()` chose (deterministic by priority-then-id, immaterial here) ends
    # up `doing`; the other stays `ready` -- both are committed either way, which is the property
    # under test.
    states = {backlog.load(swept).state, backlog.load(target).state}
    assert states == {"ready", "doing"}


def test_a_transcript_written_mid_turn_does_not_dirty_the_tree_under_places_local(repo: Path, limits: Guardrails) -> None:
    """S237's regression: under `Places.local`, the ledger nests inside the workspace `tree_clean`
    inspects, so the executor's own raw transcript is an untracked file the gate used to count as
    the agent's uncommitted work -- including the transcript of the very turn being judged."""

    class TranscriptWritingExecutor(FakeExecutor):
        """Matches what the real executor does: writes its raw transcript into `runs_dir` as a
        side effect of running, before `take_turn` ever reaches the gate."""

        def __call__(self, frame: Mapping[str, Any], workspace: Path, limits: Guardrails, **kwargs: Any) -> RunResult:
            result = super().__call__(frame, workspace, limits, **kwargs)
            kwargs["runs_dir"].mkdir(parents=True, exist_ok=True)
            result.transcript_path.write_text('{"type": "assistant"}\n', encoding="utf-8")
            return result

    seed_item(repo)
    executor = TranscriptWritingExecutor(proposal={"event": "priority_set", "priority": 5})

    take(repo, executor, limits)

    # Nothing about the transcript itself is asserted here -- only that its presence does not
    # register as dirt in the tree the `done` gate later inspects (`verify.tree_clean`).
    assert git(repo, "status", "--porcelain") == ""
