"""`build_argv` unit-level: no subprocess, no pinned binary, checkable from the argv alone."""

from __future__ import annotations

from yosefactory.executor.claude import build_argv
from yosefactory.runtime.isolation import IsolationPolicy


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
