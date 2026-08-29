"""`build_argv` unit-level: no subprocess, no pinned binary, checkable from the argv alone."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yosefactory.executor import claude as claude_module
from yosefactory.executor.claude import PINNED_EFFORT, PINNED_MODEL, build_argv, render, run
from yosefactory.protocol.turn import EnforcedBy, Outcome, TurnRecord
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.isolation import IsolationPolicy

FRAME = {"goal": "g", "method": "m", "assumptions": ["a"]}


def test_no_ceiling_sends_no_flag() -> None:
    isolated = build_argv("hello", IsolationPolicy(isolated=True))
    opted_out = build_argv("hello", IsolationPolicy(isolated=False, opt_out_reason="control"))

    assert "--max-budget-usd" not in isolated
    assert "--max-budget-usd" not in opted_out


def test_workspace_scoped_emits_project_and_local_sources_but_not_safe_mode() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=False, workspace_scoped=True, opt_out_reason="control"))

    assert "--safe-mode" not in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local"


def test_workspace_scoped_does_not_gate_tool_calls_on_human_approval() -> None:
    """`run-the-loop-inside-the-container`: workspace_scoped is the posture an unattended run
    uses, so it must not require a human to approve tool calls -- there is nobody there."""
    argv = build_argv("hello", IsolationPolicy(isolated=False, workspace_scoped=True, opt_out_reason="control"))

    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"


def test_isolated_permission_mode_is_unchanged_by_the_workspace_scoped_addition() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=True))

    assert argv[argv.index("--permission-mode") + 1] == "manual"


def test_a_ceiling_is_sent_verbatim() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=True), cost_ceiling_usd=0.02)

    assert argv[argv.index("--max-budget-usd") + 1] == "0.02"


def test_the_ceiling_reaches_the_opted_out_invocation_too() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=False, opt_out_reason="control"), cost_ceiling_usd=1.5)

    assert argv[argv.index("--max-budget-usd") + 1] == "1.5"


def test_no_opinion_sends_the_pinned_model_and_effort() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=True))

    assert argv[argv.index("--model") + 1] == PINNED_MODEL
    assert argv[argv.index("--effort") + 1] == PINNED_EFFORT


def test_an_override_is_sent_verbatim() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=True), model="claude-opus-5", effort="high")

    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[argv.index("--effort") + 1] == "high"


def test_model_and_effort_reach_the_opted_out_invocation_too() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=False, opt_out_reason="control"))

    assert argv[argv.index("--model") + 1] == PINNED_MODEL
    assert argv[argv.index("--effort") + 1] == PINNED_EFFORT


# carry-inherited-context-into-the-turn / D030: `context` renders between the frame and `invocation`.


def test_no_context_renders_nothing_extra() -> None:
    assert render(FRAME) == render(FRAME, None)
    assert "Inherited context" not in render(FRAME)


def test_an_empty_context_renders_nothing_extra() -> None:
    assert "Inherited context" not in render(FRAME, {})


def test_context_renders_between_the_frame_and_the_invocation() -> None:
    context = {"gate_rejection": {"report": "VERIFICATION FAILED: boom", "attempt": 1}}
    rendered = render(FRAME, context)

    frame_end = rendered.index("assumptions:")
    context_start = rendered.index("Inherited context")
    assert frame_end < context_start
    assert "VERIFICATION FAILED: boom" in rendered


def test_every_context_source_renders() -> None:
    context = {
        "gate_rejection": {"report": "rep", "attempt": 1},
        "answer": "use the raw tier",
        "prior_failure": {"reason": "boom", "retryable": True, "attempt": 2},
        "ended": {"event": "reclaimed", "reason": "lease expired"},
    }
    rendered = render(FRAME, context)

    assert "rep" in rendered
    assert "use the raw tier" in rendered
    assert "boom" in rendered and "retryable: True" in rendered
    assert "reclaimed" in rendered and "lease expired" in rendered


def _stub_govern(*args: Any, **kwargs: Any) -> TurnRecord:
    """No subprocess: `run`'s own transcript-path selection is what's under test, not the
    supervisor's process handling (covered live in `tests/executor/test_integration.py`)."""
    return TurnRecord(
        run_id="r1",
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:00:01Z",
        outcome=Outcome.ADVANCED,
        enforced_by=EnforcedBy.AGENT,
        dirty=False,
        isolated=True,
        note="completed; exit=0",
    )


def test_transcripts_dir_given_writes_the_transcript_there_not_under_runs_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """K D034's own receipt at the executor seam: the raw stream lands wherever `transcripts_dir`
    points, distinct from `runs_dir` (the ledger's `.start`/terminal-record stream). Fails before
    this change existed -- `run` took no `transcripts_dir` parameter at all and always wrote under
    `runs_dir`, so this configuration (the two split apart) was not expressible."""
    monkeypatch.setattr(claude_module, "govern", _stub_govern)
    runs_dir = tmp_path / "ledger" / "runs"
    transcripts_dir = tmp_path / "runner" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    # Written *before* `run()` is called: `run`'s own `StreamReader` is constructed against whatever
    # path it computes for the transcript, and `classify()` polls that path on demand -- so a
    # terminal event sitting at the right path is how this proves *which* path `run` chose, without
    # needing a real subprocess to write there.
    (transcripts_dir / "r1.stream.jsonl").write_text(
        json.dumps({"type": "result", "usage": {}, "total_cost_usd": 0.0, "num_turns": 1}) + "\n", encoding="utf-8"
    )

    result = run(
        FRAME,
        tmp_path,
        Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1, question_deadline_hours=24, max_attempts=3),
        run_id="r1",
        runs_dir=runs_dir,
        transcripts_dir=transcripts_dir,
    )

    assert result.transcript_path == transcripts_dir / "r1.stream.jsonl"
    assert not runs_dir.exists()


def test_transcripts_dir_omitted_falls_back_to_runs_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Inert by default (K D034): every caller that predates `Places.transcripts` passes only
    `runs_dir`, and must keep getting exactly the location it always wrote to."""
    monkeypatch.setattr(claude_module, "govern", _stub_govern)
    runs_dir = tmp_path / "ledger" / "runs"
    runs_dir.mkdir(parents=True)

    result = run(
        FRAME,
        tmp_path,
        Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1, question_deadline_hours=24, max_attempts=3),
        run_id="r1",
        runs_dir=runs_dir,
    )

    assert result.transcript_path == runs_dir / "r1.stream.jsonl"
