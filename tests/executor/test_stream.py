"""The verdict rules, driven from event shapes recorded off the real binary."""

from __future__ import annotations

import json
from pathlib import Path

from yosefactory.executor.outcome import FailureKind, RunOutcome
from yosefactory.executor.stream import SIGTERM_EXIT, StreamReader
from yosefactory.protocol.turn import Outcome

INIT = {
    "type": "system",
    "subtype": "init",
    "memory_paths": [],
    "mcp_servers": [],
    "skills": [],
    "plugins": [],
    "permissionMode": "manual",
}
TURN = {"type": "system", "subtype": "post_turn_summary", "needs_action": False}
SUCCESS = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "stop_reason": "end_turn",
    "terminal_reason": "completed",
    "num_turns": 1,
    "permission_denials": [],
    "api_error_status": None,
    "total_cost_usd": 0.24,
    "usage": {"input_tokens": 2, "output_tokens": 4},
}


def write(path: Path, *events: dict) -> StreamReader:
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return StreamReader(path)


def test_exit_zero_without_a_terminal_event_is_failure(tmp_path: Path) -> None:
    """The rule the whole reader exists for: a silent success is the failure it must not report."""
    reader = write(tmp_path / "s.jsonl", INIT, TURN)
    assert reader.classify(0) == (RunOutcome.FAILED, FailureKind.BAD_OUTPUT, "no terminal event")


def test_a_turn_ending_is_not_the_run_ending(tmp_path: Path) -> None:
    reader = write(tmp_path / "s.jsonl", INIT, TURN, TURN)
    assert reader.turns_taken() == 2
    assert reader.terminal is None


def test_terminal_event_is_the_verdict(tmp_path: Path) -> None:
    reader = write(tmp_path / "s.jsonl", INIT, TURN, SUCCESS)
    assert reader.classify(0)[0] is RunOutcome.SUCCESS


def test_a_nonzero_exit_does_not_overrule_a_terminal_success(tmp_path: Path) -> None:
    """The exit code is evidence. The agent said it finished, so it finished."""
    reader = write(tmp_path / "s.jsonl", INIT, SUCCESS)
    assert reader.classify(1)[0] is RunOutcome.SUCCESS


def test_rate_limit_is_never_folded_into_a_generic_failure(tmp_path: Path) -> None:
    """A starved factory and a broken model have opposite fixes."""
    reader = write(tmp_path / "s.jsonl", INIT, {"type": "rate_limit_event", "rate_limit_info": {}})
    _, kind, _ = reader.classify(1)
    assert kind is FailureKind.RATE_LIMIT

    limited = write(tmp_path / "t.jsonl", INIT, {**SUCCESS, "is_error": True, "subtype": "error", "api_error_status": 429})
    assert limited.classify(1)[1] is FailureKind.RATE_LIMIT


def test_auth_failure_is_its_own_kind(tmp_path: Path) -> None:
    reader = write(tmp_path / "s.jsonl", INIT, {**SUCCESS, "is_error": True, "subtype": "error", "api_error_status": 401})
    assert reader.classify(1)[1] is FailureKind.AUTH


def test_permission_denial_and_turn_limit_are_not_failures(tmp_path: Path) -> None:
    denied = write(tmp_path / "d.jsonl", INIT, {**SUCCESS, "permission_denials": [{"tool": "Bash"}]})
    assert denied.classify(0)[0] is RunOutcome.NEEDS_APPROVAL

    capped = write(tmp_path / "c.jsonl", INIT, {**SUCCESS, "is_error": True, "subtype": "error_max_turns"})
    assert capped.classify(1)[0] is RunOutcome.TURN_LIMIT


def test_termination_reads_as_cancelled(tmp_path: Path) -> None:
    reader = write(tmp_path / "s.jsonl", INIT, TURN)
    assert reader.classify(SIGTERM_EXIT)[0] is RunOutcome.CANCELLED


def test_a_partial_final_line_is_not_a_malformed_stream(tmp_path: Path) -> None:
    """The reader polls a file the agent is still writing; a half-written line is normal."""
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(INIT) + "\n" + json.dumps(TURN)[:20], encoding="utf-8")
    reader = StreamReader(path)
    assert reader.turns_taken() == 0

    path.write_text(json.dumps(INIT) + "\n" + json.dumps(TURN) + "\n", encoding="utf-8")
    assert reader.turns_taken() == 1


def test_init_reports_the_leaks_isolation_is_asserted_from(tmp_path: Path) -> None:
    """Flags express intent; this is the agent stating what it actually loaded."""
    clean = write(tmp_path / "clean.jsonl", INIT)
    clean.poll()
    assert clean.init is not None
    assert clean.init.leaks == ()

    leaky = write(tmp_path / "leaky.jsonl", {**INIT, "memory_paths": ["CLAUDE.md"], "mcp_servers": [{"name": "a2web"}]})
    leaky.poll()
    assert leaky.init is not None
    assert leaky.init.leaks == ("memory=1", "mcp=1")


def test_host_commands_are_a_leak_because_they_carry_instructions(tmp_path: Path) -> None:
    reader = write(tmp_path / "commands.jsonl", {**INIT, "slash_commands": ["compact", "review"]})
    reader.poll()

    assert reader.init is not None
    assert reader.init.leaks == ("commands=2",)


def test_a_registered_plugin_is_residue_and_not_a_breach(tmp_path: Path) -> None:
    """The measured floor: safe mode registers one host plugin that no flag unregisters.

    With commands disabled it supplies no skills and no commands, so it puts nothing in front of the
    model. Failing the run on it would fail every isolated run there is; dropping it silently would
    lose the only record that the floor is not zero.
    """
    reader = write(tmp_path / "residue.jsonl", {**INIT, "plugins": [{"name": "skill-creator"}]})
    reader.poll()

    assert reader.init is not None
    assert reader.init.leaks == ()
    assert reader.init.residue == ("plugins=1",)


def test_outcomes_narrow_to_the_four_the_record_holds(tmp_path: Path) -> None:
    from yosefactory.executor.outcome import RunResult, Usage

    def narrowed(outcome: RunOutcome) -> Outcome:
        return RunResult(outcome=outcome, usage=Usage(), transcript_path=tmp_path, exit_code=0, dirty=False).protocol_outcome

    assert narrowed(RunOutcome.SUCCESS) is Outcome.ADVANCED
    assert narrowed(RunOutcome.NEEDS_APPROVAL) is Outcome.BLOCKED
    assert narrowed(RunOutcome.TURN_LIMIT) is Outcome.FAILED
    # nothing-ready is a judgement about the backlog, made before an executor starts.
    assert Outcome.NOTHING_READY not in {narrowed(outcome) for outcome in RunOutcome}


def test_the_failure_kind_survives_into_the_record_note(tmp_path: Path) -> None:
    """Until a record can hold a typed failure kind, it travels here rather than being dropped."""
    from yosefactory.executor.outcome import RunResult, Usage

    result = RunResult(
        outcome=RunOutcome.FAILED,
        usage=Usage(),
        transcript_path=tmp_path,
        exit_code=1,
        dirty=False,
        failure_kind=FailureKind.RATE_LIMIT,
    )
    assert "kind=rate_limit" in result.note()
