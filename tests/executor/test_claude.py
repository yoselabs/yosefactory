"""`build_argv` unit-level: no subprocess, no pinned binary, checkable from the argv alone."""

from __future__ import annotations

from yosefactory.executor.claude import build_argv
from yosefactory.runtime.isolation import IsolationPolicy


def test_no_ceiling_sends_no_flag() -> None:
    isolated = build_argv("hello", IsolationPolicy(isolated=True))
    opted_out = build_argv("hello", IsolationPolicy(isolated=False, opt_out_reason="control"))

    assert "--max-budget-usd" not in isolated
    assert "--max-budget-usd" not in opted_out


def test_a_ceiling_is_sent_verbatim() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=True), cost_ceiling_usd=0.02)

    assert argv[argv.index("--max-budget-usd") + 1] == "0.02"


def test_the_ceiling_reaches_the_opted_out_invocation_too() -> None:
    argv = build_argv("hello", IsolationPolicy(isolated=False, opt_out_reason="control"), cost_ceiling_usd=1.5)

    assert argv[argv.index("--max-budget-usd") + 1] == "1.5"
