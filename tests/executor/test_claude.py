"""`build_argv` unit-level: no subprocess, no pinned binary, checkable from the argv alone."""

from __future__ import annotations

from yosefactory.executor.claude import PINNED_EFFORT, PINNED_MODEL, build_argv, render
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
