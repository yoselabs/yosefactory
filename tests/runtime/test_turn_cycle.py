"""One turn of the reducer.

The acceptance test is `test_two_turns_share_nothing_but_the_repository`: turn one plans from an
empty backlog, turn two — a separate call, sharing no state — picks up what it committed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from yosefactory.executor.outcome import FailureKind, RunOutcome, RunResult, Usage
from yosefactory.protocol import backlog
from yosefactory.protocol.eventlog import LogError
from yosefactory.protocol.turn import EnforcedBy, Outcome
from yosefactory.runtime import turn
from yosefactory.runtime.config import Guardrails
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
    return Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1)


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


class FakeExecutor:
    """Writes a scripted proposal where the turn asked for it, and remembers being called."""

    def __init__(self, proposal: Any = None, *, outcome: RunOutcome = RunOutcome.SUCCESS, raw: str | None = None) -> None:
        self.proposal = proposal
        self.raw = raw
        self.outcome = outcome
        self.calls: list[Mapping[str, Any]] = []
        self.log_at_call: list[str] = []

    def __call__(
        self,
        frame: Mapping[str, Any],
        workspace: Path,
        limits: Guardrails,
        *,
        run_id: str,
        runs_dir: Path,
    ) -> RunResult:
        self.calls.append(frame)
        self.log_at_call.append(git(workspace, "log", "--oneline"))
        path = Path(str(frame["proposal_path"]))
        if self.raw is not None:
            path.write_text(self.raw, encoding="utf-8")
        elif self.proposal is not None:
            path.write_text(json.dumps(self.proposal), encoding="utf-8")
        return RunResult(
            outcome=self.outcome,
            usage=Usage(),
            transcript_path=runs_dir / f"{run_id}.stream.jsonl",
            exit_code=0,
            dirty=False,
            failure_kind=None if self.outcome is RunOutcome.SUCCESS else FailureKind.CRASH,
            detail="",
        )


def take(repo: Path, executor: Any, limits: Guardrails, **kwargs: Any) -> Any:
    kwargs.setdefault("test_command", TRUE_COMMAND)
    return turn.take_turn(repo, executor, limits=limits, owner="tester", skill=SKILL, proposal_dir=repo.parent, **kwargs)


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
    from yosefactory.protocol import question

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


def test_a_done_with_a_passing_gate_advances(repo: Path, limits: Guardrails) -> None:
    item = seed_item(repo)
    executor = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"})

    record = take(repo, executor, limits)

    assert record.outcome is Outcome.ADVANCED
    assert record.enforced_by is EnforcedBy.AGENT
    assert backlog.load(item).state == "done"


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
