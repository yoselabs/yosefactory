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
    return Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1, question_deadline_hours=24)


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
    ) -> None:
        self.proposal = proposal
        self.raw = raw
        self.outcome = outcome
        self.kind = kind if kind is not None else FailureKind.CRASH
        self.calls: list[Mapping[str, Any]] = []
        self.invocations: list[Invocation | None] = []
        self.log_at_call: list[str] = []
        self.workspaces: list[Path] = []

    def __call__(
        self,
        frame: Mapping[str, Any],
        workspace: Path,
        limits: Guardrails,
        *,
        run_id: str,
        runs_dir: Path,
        invocation: Invocation | None = None,
    ) -> RunResult:
        self.calls.append(frame)
        self.invocations.append(invocation)
        self.log_at_call.append(git(workspace, "log", "--oneline"))
        self.workspaces.append(workspace)
        assert invocation is not None and invocation.proposal_path is not None
        path = invocation.proposal_path
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
    assert backlog.load(item_path).state == "doing"


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
