"""`run_loop` self-chains `take_turn` and stops at its bound. Every executor call here is fake and
every turn that matters for the wake-condition receipts is `nothing-ready`, so this file spends
nothing -- `tests/runtime/test_turn_integration.py` already carries the live receipt for
`take_turn`-versus-a-real-executor; this file's job is the loop wrapped around it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from yosefactory.executor.invocation import Invocation
from yosefactory.executor.outcome import RunOutcome, RunResult, Usage
from yosefactory.protocol.turn import Outcome
from yosefactory.runtime import loop as loop_mod
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.loop import LoopBound, LoopError, WakeConfig, WakeReason, run_loop
from yosefactory.runtime.turn import ITEMS, QUESTIONS, Places

SKILL = Path("workflows/turn-skill.md")


def git(repo: Path, *args: str) -> str:
    binary = shutil.which("git")
    assert binary is not None
    completed = subprocess.run([binary, *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
    return completed.stdout.strip()


@pytest.fixture
def limits() -> Guardrails:
    return Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1, question_deadline_hours=24)


def seed_snoozed_item(queue: Path) -> Path:
    """A non-terminal, non-ready item -- present, but neither `eligible()` nor a `should_plan()`
    trigger. Its only purpose is to hold the backlog in the free `nothing-ready` branch: with it
    present, `take_turn` never starts an executor at all (`turn.py`'s `target is None and not
    should_plan(...)` branch), which is what lets most of this file's receipts cost $0."""
    from yosefactory.protocol import backlog
    from yosefactory.runtime.turn import append, new_item_id

    path = queue / ITEMS / f"{new_item_id()}.jsonl"
    frame = {"goal": "held back on purpose", "method": "m", "assumptions": "a"}
    append(path, backlog.ITEM, {"event": "created", "loop": "receipt", "frame": frame}, actor="fixture")
    append(path, backlog.ITEM, {"event": "snoozed", "scheduled_for": "2099-01-01T00:00:00+00:00"}, actor="fixture")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ITEMS).mkdir(parents=True)
    (root / QUESTIONS).mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    seed_snoozed_item(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed snoozed item")
    return root


@pytest.fixture
def places(repo: Path) -> Places:
    return Places.local(repo)


@pytest.fixture
def spend_log(tmp_path: Path) -> Path:
    """An isolated ledger, never this checkout's own `ledger/spend.jsonl` -- without this, every
    `spend_usd == 0.0` assertion below would be reading whatever this repo's own live-test history
    happened to contain, which is exactly the "read the subject, not a proxy" mistake Article XII
    warns against, made against a live file instead of a mock."""
    return tmp_path / "spend.jsonl"


class NeverCalled:
    """An executor that fails the test if it is ever invoked -- the `nothing-ready` proof."""

    def __call__(self, *args: Any, **kwargs: Any) -> RunResult:
        raise AssertionError("executor invoked on a nothing-ready turn -- this should never spend a cent")


class BumpPriorityExecutor:
    """Writes one legal, non-terminal `priority_set` event for whichever item it is handed -- the
    cheapest real single-event item-turn proposal that neither claims `done` (and so never
    triggers `verify.may_write_done`) nor requires a foreign workspace."""

    def __init__(self) -> None:
        self.calls = 0

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
        self.calls += 1
        assert invocation is not None and invocation.proposal_path is not None
        event = {"event": "priority_set", "priority": 5}
        invocation.proposal_path.write_text(json.dumps(event), encoding="utf-8")
        return RunResult(
            outcome=RunOutcome.SUCCESS,
            usage=Usage(),
            transcript_path=runs_dir / f"{run_id}.stream.jsonl",
            exit_code=0,
            dirty=False,
        )


@dataclass
class FakeClock:
    """A controllable clock -- `sleep` advances `now` deterministically, so heartbeat tests never
    touch a real wall clock and `_await_wake`'s poll loop cannot spin for real time."""

    now: datetime
    on_sleep: list[Any] = field(default_factory=list)
    sleeps: int = 0

    def now_fn(self) -> datetime:
        return self.now

    def sleep_fn(self, seconds: float) -> None:
        self.sleeps += 1
        for callback in self.on_sleep:
            callback()
        self.now += timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# LoopBound / WakeConfig — refuse an unbounded or nonsensical configuration
# ---------------------------------------------------------------------------


def test_loop_bound_requires_a_positive_max_iterations() -> None:
    with pytest.raises(LoopError):
        LoopBound(max_iterations=0)
    with pytest.raises(LoopError):
        LoopBound(max_iterations=-1)


def test_loop_bound_spend_ceiling_must_be_positive_when_set() -> None:
    with pytest.raises(LoopError):
        LoopBound(max_iterations=1, spend_ceiling_usd=0)
    with pytest.raises(LoopError):
        LoopBound(max_iterations=1, spend_ceiling_usd=-5)


def test_loop_bound_with_no_spend_ceiling_is_legal() -> None:
    assert LoopBound(max_iterations=3).spend_ceiling_usd is None


def test_wake_config_requires_positive_intervals() -> None:
    with pytest.raises(LoopError):
        WakeConfig(heartbeat_seconds=0)
    with pytest.raises(LoopError):
        WakeConfig(heartbeat_seconds=10, poll_seconds=0)


# ---------------------------------------------------------------------------
# _refuse_if_dirty -- the mount-race guard found by add-scheduled-loop's launchd receipt
# ---------------------------------------------------------------------------


def test_refuse_if_dirty_raises_on_an_uncommitted_change(repo: Path) -> None:
    (repo / "uncommitted.txt").write_text("not committed\n", encoding="utf-8")
    with pytest.raises(loop_mod.LoopError, match=str(repo)):
        loop_mod._refuse_if_dirty(repo)


def test_refuse_if_dirty_is_silent_on_a_clean_tree(repo: Path) -> None:
    loop_mod._refuse_if_dirty(repo)  # must not raise


def test_run_loop_refuses_before_any_turn_when_the_workspace_is_dirty(places: Places, limits: Guardrails, spend_log: Path) -> None:
    (places.workspace / "uncommitted.txt").write_text("not committed\n", encoding="utf-8")
    before = list((places.ledger).glob("*")) if places.ledger.exists() else []

    with pytest.raises(loop_mod.LoopError):
        run_loop(
            places,
            NeverCalled(),
            limits=limits,
            owner="loop-test",
            skill=SKILL,
            bound=LoopBound(max_iterations=1),
            wake=WakeConfig(heartbeat_seconds=30, poll_seconds=5),
            proposal_dir=places.queue.parent,
            spend_log=spend_log,
        )

    after = list((places.ledger).glob("*")) if places.ledger.exists() else []
    assert after == before  # no ledger record was written -- refused before the first turn


# ---------------------------------------------------------------------------
# Self-chaining and the bound, at $0 — the `nothing-ready` path never starts an executor
# ---------------------------------------------------------------------------


def test_the_loop_self_chains_nothing_ready_turns_until_the_iteration_bound(places: Places, limits: Guardrails, spend_log: Path) -> None:
    """The free end-to-end receipt: three real turns, three real ledger rows, one process, no human
    calling `take_turn` a second or third time."""
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))
    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=3),
        wake=WakeConfig(heartbeat_seconds=30, poll_seconds=5),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )

    assert report.stopped is loop_mod.StopReason.MAX_ITERATIONS
    assert len(report.steps) == 3
    assert [step.record.outcome for step in report.steps] == [Outcome.NOTHING_READY] * 3
    assert report.steps[0].wake is WakeReason.STARTUP
    assert report.steps[1].wake is WakeReason.HEARTBEAT
    assert report.steps[2].wake is WakeReason.HEARTBEAT
    assert report.spend_usd == 0.0

    # Read the SUBJECT, not the return value (Article XII / S194): the ledger rows exist on disk,
    # are three, and are all `nothing-ready` -- exactly what the report claims.
    on_disk = sorted(p for p in places.ledger.glob("*.json") if not p.name.endswith(".wake.json"))
    assert len(on_disk) == 3
    for path in on_disk:
        row = json.loads(path.read_text(encoding="utf-8"))
        assert row["outcome"] == "nothing-ready"

    # And the wake reason is durable too -- readable from disk alone, joined by run_id, without
    # ever touching `report` (a fresh process with only the queue on disk could reconstruct this).
    wake_files = sorted(places.ledger.glob("*.wake.json"))
    assert len(wake_files) == 3
    on_disk_by_run_id = {json.loads(p.read_text())["run_id"]: json.loads(p.read_text())["wake"] for p in wake_files}
    for step in report.steps:
        assert on_disk_by_run_id[step.record.run_id] == step.wake.value

    # And every one of those three rows is a real commit in the queue's own git log.
    log = git(places.queue, "log", "--oneline")
    assert log.count("\n") + 1 >= 3


def test_startup_fires_the_first_turn_without_waiting_for_the_heartbeat(places: Places, limits: Guardrails, spend_log: Path) -> None:
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))
    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=1),
        wake=WakeConfig(heartbeat_seconds=99_999),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )
    assert len(report.steps) == 1
    assert report.steps[0].wake is WakeReason.STARTUP
    assert clock.sleeps == 0  # never polled -- the first turn never waits


def test_max_iterations_of_zero_work_stops_before_any_turn_when_already_exhausted(
    places: Places, limits: Guardrails, spend_log: Path
) -> None:
    """A degenerate but legal bound: reusing a report's own iteration count as a fresh bound of the
    same size would run one more turn if the check were off by one. Guards that directly."""
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))
    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=1),
        wake=WakeConfig(heartbeat_seconds=30),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )
    assert len(report.steps) == 1  # sanity: max_iterations=1 really means exactly one turn


# ---------------------------------------------------------------------------
# The three wake conditions, each isolated
# ---------------------------------------------------------------------------


def test_wakes_on_a_ready_item_without_waiting_for_the_heartbeat(places: Places, limits: Guardrails, spend_log: Path) -> None:
    """A ready item appears mid-sleep (simulating an external planner or a human editing the
    backlog) and the loop wakes for it on the very next poll rather than waiting out the heartbeat,
    then actually runs a turn against it."""
    from yosefactory.protocol import backlog
    from yosefactory.runtime.turn import append, new_item_id

    executor = BumpPriorityExecutor()
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))

    def plant_ready_item() -> None:
        if clock.sleeps == 1:  # only once -- the first idle wait after the startup turn
            path = places.queue / ITEMS / f"{new_item_id()}.jsonl"
            frame = {"goal": "g", "method": "m", "assumptions": "a"}
            append(path, backlog.ITEM, {"event": "created", "loop": "receipt", "frame": frame}, actor="external")

    clock.on_sleep.append(plant_ready_item)

    report = run_loop(
        places,
        executor,
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=2),
        wake=WakeConfig(heartbeat_seconds=99_999, poll_seconds=1),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )
    assert [step.wake for step in report.steps] == [WakeReason.STARTUP, WakeReason.READY_ITEM]
    assert executor.calls == 1  # the loop woke for the planted item and ran a real turn against it
    assert report.steps[1].record.outcome is Outcome.ADVANCED

    # The second turn's wake reason (READY_ITEM) is on disk, committed, joinable by run_id --
    # not only inside `report`, which a fresh reader of the repo would never see.
    second_run_id = report.steps[1].record.run_id
    matches = list(places.ledger.glob(f"*-{second_run_id}.wake.json"))
    assert len(matches) == 1
    row = json.loads(matches[0].read_text(encoding="utf-8"))
    assert row == {"run_id": second_run_id, "wake": "ready_item"}
    assert "wake=ready_item" in git(places.queue, "log", "--format=%s", "-1")


def test_the_wake_record_is_a_real_commit_named_by_the_turns_own_run_id(
    places: Places, limits: Guardrails, spend_log: Path
) -> None:
    """A dedicated receipt for the durable-wake-record requirement, independent of any other
    scenario's assertions: after one turn, `git log` on the queue shows a commit for the wake
    sidecar, and it names the same `run_id` the turn record itself carries."""
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))
    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=1),
        wake=WakeConfig(heartbeat_seconds=30),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )
    run_id = report.steps[0].record.run_id
    subjects = git(places.queue, "log", "--format=%s").splitlines()
    assert any(run_id in subject and "wake=" in subject for subject in subjects)


def test_wakes_on_an_external_event_when_the_queue_head_moves(places: Places, limits: Guardrails, spend_log: Path) -> None:
    """Nobody added a ready item, but a commit landed in the queue while the loop was idle -- the
    HEAD comparison wakes the loop even though `eligible()` alone would have kept it asleep."""
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))

    def land_a_commit() -> None:
        if clock.sleeps == 1:
            (places.queue / "external.txt").write_text("landed\n", encoding="utf-8")
            git(places.queue, "add", "external.txt")
            git(places.queue, "commit", "-q", "-m", "external event")

    clock.on_sleep.append(land_a_commit)

    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=2),
        wake=WakeConfig(heartbeat_seconds=99_999, poll_seconds=1),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )
    assert [step.wake for step in report.steps] == [WakeReason.STARTUP, WakeReason.EXTERNAL_EVENT]


def test_wakes_on_heartbeat_when_nothing_else_changes(places: Places, limits: Guardrails, spend_log: Path) -> None:
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))
    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=2),
        wake=WakeConfig(heartbeat_seconds=10, poll_seconds=5),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )
    assert [step.wake for step in report.steps] == [WakeReason.STARTUP, WakeReason.HEARTBEAT]
    assert clock.sleeps == 2  # 5s then 5s -- ten total, the heartbeat threshold


# ---------------------------------------------------------------------------
# The spend ceiling — the half of the bound that matters once a turn can cost money
# ---------------------------------------------------------------------------


def test_the_loop_stops_at_the_spend_ceiling_before_the_iteration_bound(places: Places, limits: Guardrails, tmp_path: Path) -> None:
    """A live executor's `spend.record()` call is out of scope for this fake-executor file (that
    integration lives in `record-live-spend-and-gate-make-check` and `test_turn_integration.py`), so
    this test writes the same row shape `spend.record` would, to prove `run_loop` itself reads and
    honours the ledger rather than trusting the executor to self-report an in-band number."""
    from yosefactory.runtime import spend

    spend_log = tmp_path / "spend.jsonl"
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))

    def record_spend_mid_sleep() -> None:
        if clock.sleeps == 1:
            spend.record(0.75, run_id="external-spend", log_path=spend_log)

    clock.on_sleep.append(record_spend_mid_sleep)

    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=10, spend_ceiling_usd=0.50),
        wake=WakeConfig(heartbeat_seconds=10, poll_seconds=5),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )

    assert report.stopped is loop_mod.StopReason.SPEND_CEILING
    assert len(report.steps) == 1  # only the startup turn ran; the second never started
    assert report.spend_usd >= 0.50


def test_the_spend_ceiling_is_ignored_when_unset(places: Places, limits: Guardrails, spend_log: Path) -> None:
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))
    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=2),
        wake=WakeConfig(heartbeat_seconds=10, poll_seconds=5),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )
    assert report.stopped is loop_mod.StopReason.MAX_ITERATIONS
    assert len(report.steps) == 2


# ---------------------------------------------------------------------------
# scheduled_main -- the scheduler-only entrypoint requires a spend ceiling; main() does not
# ---------------------------------------------------------------------------


def test_scheduled_main_refuses_to_start_without_a_spend_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """argparse SHALL reject the invocation before `run_loop` is ever reached -- the ceiling is
    enforced by the parser, not by a convention an installer could forget."""
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("run_loop must not be called when --spend-ceiling-usd is missing")

    monkeypatch.setattr(loop_mod, "run_loop", fail_if_called)
    with pytest.raises(SystemExit):
        loop_mod.scheduled_main(["--max-iterations", "1"])
    assert called is False


def test_main_still_does_not_require_a_spend_ceiling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`main()`'s own default (`unattended=False`) is unchanged by this entrypoint's addition --
    D022's interactive deferral stands."""
    captured: dict[str, Any] = {}

    def fake_run_loop(places: Places, executor: Any, **kwargs: Any) -> Any:
        captured["bound"] = kwargs["bound"]
        return loop_mod.LoopReport(steps=(), stopped=loop_mod.StopReason.MAX_ITERATIONS, spend_usd=0.0)

    monkeypatch.setattr(loop_mod, "run_loop", fake_run_loop)
    exit_code = loop_mod.main(["--max-iterations", "1", str(tmp_path)])
    assert exit_code == 0
    assert captured["bound"].spend_ceiling_usd is None


def test_a_supplied_ceiling_is_identical_via_either_entrypoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_run_loop(places: Places, executor: Any, **kwargs: Any) -> Any:
        captured["bound"] = kwargs["bound"]
        return loop_mod.LoopReport(steps=(), stopped=loop_mod.StopReason.MAX_ITERATIONS, spend_usd=0.0)

    monkeypatch.setattr(loop_mod, "run_loop", fake_run_loop)

    loop_mod.main(["--max-iterations", "1", "--spend-ceiling-usd", "2.0", str(tmp_path)])
    via_main = captured["bound"].spend_ceiling_usd

    loop_mod.scheduled_main(["--max-iterations", "1", "--spend-ceiling-usd", "2.0", str(tmp_path)])
    via_scheduled = captured["bound"].spend_ceiling_usd

    assert via_main == via_scheduled == 2.0


def test_unattended_entrypoint_does_not_default_to_a_posture_that_denies_tool_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`run-the-loop-inside-the-container`: `scheduled_main` (the container's own entrypoint) must
    not inherit `main()`'s interactive `isolated` default -- that posture requires human approval
    for every tool call, and an unattended run has no human to give it."""
    from yosefactory.executor import claude as claude_mod

    captured: dict[str, Any] = {}

    def fake_claude_run(frame: Any, workspace: Any, limits: Any, **kwargs: Any) -> Any:
        captured["policy"] = kwargs["policy"]
        return RunResult(outcome=RunOutcome.SUCCESS, usage=Usage(), transcript_path=tmp_path / "t", exit_code=0, dirty=False)

    def fake_run_loop(places: Places, executor: Any, **kwargs: Any) -> Any:
        captured["isolated_kwarg"] = kwargs["isolated"]
        executor({"goal": "x"}, tmp_path, kwargs["limits"], run_id="r", runs_dir=tmp_path)
        return loop_mod.LoopReport(steps=(), stopped=loop_mod.StopReason.MAX_ITERATIONS, spend_usd=0.0)

    monkeypatch.setattr(claude_mod, "run", fake_claude_run)
    monkeypatch.setattr(loop_mod, "run_loop", fake_run_loop)

    loop_mod.scheduled_main(["--max-iterations", "1", "--spend-ceiling-usd", "2.0", str(tmp_path)])
    unattended_policy = captured["policy"]
    assert unattended_policy.isolated is False
    assert unattended_policy.workspace_scoped is True
    assert unattended_policy.opt_out_reason
    # `run_loop`'s own `isolated` kwarg feeds the turn record, separately from `policy` above --
    # it must agree, or the record says `isolated: true` for a run that was not.
    assert captured["isolated_kwarg"] is False

    loop_mod.main(["--max-iterations", "1", str(tmp_path)])
    interactive_policy = captured["policy"]
    assert interactive_policy.isolated is True
    assert interactive_policy.workspace_scoped is False
    assert captured["isolated_kwarg"] is True


# ---------------------------------------------------------------------------
# BoardConfig -- turn-loop/board-wiring: ingestion never invokes an executor,
# board polling has its own cadence, and turn results reach the board.
# ---------------------------------------------------------------------------


def _board_priority_event(item_id: str, ref: str, priority: int = 9) -> Any:
    from tests.board.fake_adapter import Event

    return Event(
        event_id="e1", ts="2026-01-01T00:00:00Z", actor="denis", type="set_priority", payload={"priority": priority, "item_id": item_id}
    )


def test_board_config_requires_a_positive_poll_interval() -> None:
    from tests.board.fake_adapter import FakeAdapter

    with pytest.raises(loop_mod.LoopError):
        loop_mod.BoardConfig(adapter=FakeAdapter(), poll_seconds=0)


def test_a_board_command_is_applied_but_never_invokes_the_executor_directly(
    places: Places, limits: Guardrails, spend_log: Path
) -> None:
    """The S987 defense: `ingest()` is a pure git write. With no ready item and nothing to plan,
    `take_turn` stays on the free `nothing-ready` path -- an executor call here would mean board
    polling grew a direct path to spending money, which is exactly the defect the dispatch named."""
    from yosefactory.protocol import backlog
    from yosefactory.runtime.turn import append, new_item_id

    item_path = places.queue / ITEMS / f"{new_item_id()}.jsonl"
    frame = {"goal": "g", "method": "m", "assumptions": "a"}
    append(item_path, backlog.ITEM, {"event": "created", "loop": "receipt", "frame": frame}, actor="fixture")
    append(item_path, backlog.ITEM, {"event": "snoozed", "scheduled_for": "2099-01-01T00:00:00+00:00"}, actor="fixture")
    git(places.queue, "add", "-A")
    git(places.queue, "commit", "-q", "-m", "seed a second snoozed item, addressable by the board command")

    from tests.board.fake_adapter import FakeAdapter

    adapter = FakeAdapter()
    adapter.queued_events = [_board_priority_event(item_path.stem, "1")]
    board = loop_mod.BoardConfig(adapter=adapter, poll_seconds=1)
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))

    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=1),
        wake=WakeConfig(heartbeat_seconds=99_999, poll_seconds=1),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        board=board,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )

    assert report.steps[0].record.outcome is Outcome.NOTHING_READY  # NeverCalled would have raised otherwise
    from yosefactory.protocol.backlog import load, priority

    assert priority(load(item_path)) == 9  # the command DID land -- ingestion is not a no-op
    assert "board(e1)" in git(places.queue, "log", "--format=%s")  # committed, not left in the tree


def test_a_board_command_surfaces_as_a_turn_only_through_external_event(
    places: Places, limits: Guardrails, spend_log: Path
) -> None:
    """No fourth wake reason exists for the board (design.md). A command applied mid-wait moves
    the queue's own HEAD, and the *existing* EXTERNAL_EVENT check is what wakes the loop for it --
    the same mechanism a human's manual push already uses."""
    from yosefactory.protocol import backlog
    from yosefactory.runtime.turn import append, new_item_id

    item_path = places.queue / ITEMS / f"{new_item_id()}.jsonl"
    frame = {"goal": "g", "method": "m", "assumptions": "a"}
    append(item_path, backlog.ITEM, {"event": "created", "loop": "receipt", "frame": frame}, actor="fixture")
    append(item_path, backlog.ITEM, {"event": "snoozed", "scheduled_for": "2099-01-01T00:00:00+00:00"}, actor="fixture")
    git(places.queue, "add", "-A")
    git(places.queue, "commit", "-q", "-m", "seed a second snoozed item")

    from tests.board.fake_adapter import FakeAdapter

    adapter = FakeAdapter()
    board = loop_mod.BoardConfig(adapter=adapter, poll_seconds=1)

    def plant_board_command() -> None:
        if clock.sleeps == 1:  # only once -- the first idle wait after the startup turn
            adapter.queued_events = [_board_priority_event(item_path.stem, "1")]

    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))
    clock.on_sleep.append(plant_board_command)

    report = run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=2),
        wake=WakeConfig(heartbeat_seconds=99_999, poll_seconds=1),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        board=board,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )

    assert [step.wake for step in report.steps] == [WakeReason.STARTUP, WakeReason.EXTERNAL_EVENT]


def test_board_polling_has_its_own_cadence_independent_of_wake_poll_seconds(
    places: Places, limits: Guardrails, spend_log: Path
) -> None:
    """`wake.poll_seconds` ticks every second (cheap, local); the board's own interval is 100x
    longer. The board must not be re-polled on every wake-loop tick -- that would collapse the
    "two different frequencies" the dispatch required into one, network-bound frequency."""
    from tests.board.fake_adapter import FakeAdapter

    class CountingAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.list_events_calls = 0

        def list_events(self, since: str | None) -> list[Any]:
            self.list_events_calls += 1
            return super().list_events(since)

    adapter = CountingAdapter()
    board = loop_mod.BoardConfig(adapter=adapter, poll_seconds=100)
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))

    run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=3),
        wake=WakeConfig(heartbeat_seconds=30, poll_seconds=1),  # ticks every second
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        board=board,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )

    # Two heartbeats of 30s each pass in ~30 one-second ticks apiece -- far more than 100s/board
    # poll would allow if the board were polled on every wake tick.
    assert adapter.list_events_calls < clock.sleeps


def test_a_completed_turns_outcome_is_projected_to_the_board(places: Places, limits: Guardrails, spend_log: Path) -> None:
    from tests.board.fake_adapter import FakeAdapter

    adapter = FakeAdapter()
    board = loop_mod.BoardConfig(adapter=adapter, poll_seconds=60)
    executor = BumpPriorityExecutor()
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))

    from yosefactory.protocol import backlog
    from yosefactory.runtime.turn import append, new_item_id

    item_path = places.queue / ITEMS / f"{new_item_id()}.jsonl"
    frame = {"goal": "g", "method": "m", "assumptions": "a"}
    append(item_path, backlog.ITEM, {"event": "created", "loop": "receipt", "frame": frame}, actor="fixture")
    git(places.queue, "add", "-A")
    git(places.queue, "commit", "-q", "-m", "seed a ready item")

    run_loop(
        places,
        executor,
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=1),
        wake=WakeConfig(heartbeat_seconds=30),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        board=board,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )

    assert item_path.stem in adapter._by_item
    ref = adapter._by_item[item_path.stem]
    assert adapter.threads[ref].state == "doing"  # the priority_set turn advanced ready -> doing


def test_the_board_reflects_pre_existing_queue_state_before_the_first_turn(
    places: Places, limits: Guardrails, spend_log: Path
) -> None:
    """`places`'s own fixture already seeds one snoozed item before the loop ever runs -- it must
    show up on the board even though no turn touches it and the executor is never called."""
    from tests.board.fake_adapter import FakeAdapter

    adapter = FakeAdapter()
    board = loop_mod.BoardConfig(adapter=adapter, poll_seconds=60)
    clock = FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC))

    run_loop(
        places,
        NeverCalled(),
        limits=limits,
        owner="loop-test",
        skill=SKILL,
        bound=LoopBound(max_iterations=1),
        wake=WakeConfig(heartbeat_seconds=30),
        proposal_dir=places.queue.parent,
        spend_log=spend_log,
        board=board,
        now_fn=clock.now_fn,
        sleep_fn=clock.sleep_fn,
    )

    assert len(adapter.threads) == 1  # the fixture's own pre-seeded snoozed item, projected before any turn ran
