## 1. Trace, don't assume

- [x] 1.1 Read `build_argv` end to end (`executor/claude.py:135`); confirm it never calls
      `subprocess.run` and never calls `resolve_version()`.
- [x] 1.2 Read `_binary()`; confirm it is `shutil.which` (a PATH lookup), raising if absent, never
      an invocation.
- [x] 1.3 Read the test's actual decorator stack as currently written
      (`@pytest.mark.usefixtures("require_pinned_claude")`), not just its body; confirm
      `require_pinned_claude` itself calls `resolve_version()`, which does spawn `claude --version`
      — the version dependency lived in the decorator, not the body.

## 2. Ungate

- [x] 2.1 Replace the module-level `pytestmark = [pytest.mark.live, skipif(...)]` in
      `tests/executor/test_integration.py` with a named `_needs_live_claude = skipif(...)`
      (matching `tests/runtime/test_turn_integration.py`'s existing convention).
- [x] 2.2 Add `@pytest.mark.live` + `@_needs_live_claude` explicitly to the five tests that
      genuinely drive `executor.claude.run(...)` against a real agent.
- [x] 2.3 `test_isolated_invocation_never_reaches_for_bare_mode`: remove
      `@pytest.mark.usefixtures("require_pinned_claude")`; keep `@_needs_live_claude` (build_argv
      still needs the binary resolvable on `PATH`, just never executed or version-checked).

## 3. Spec

- [x] 3.1 `claude-executor/live-test-gating` spec delta: MODIFIED requirement — the
      never-gated-when-no-invocation rule gains a third scenario, narrower than the first two: a
      test exempt from live-cost and version gates that still needs the binary present on `PATH`.

## 4. Design — the detector question

- [x] 4.1 Name a candidate static-property detector (AST walk over `pytest.mark.live`-marked
      tests, checking each reaches a known binary-driving symbol) in `design.md`.
- [x] 4.2 State explicitly why it is not built here (reachability, not mere reference, is the hard
      half; a naive version would misclassify the crash-gap test's own shape).
- [x] 4.3 Confirm the rejected "scheduled binary-present job" shape still fails on D111 (no daemon)
      for a single-operator repo, per `the-conformance-test-that-cannot-fail`'s own prior ruling.

## 5. Verify

- [x] 5.1 `make check` (in-container) — collection count for
      `tests/executor/test_integration.py` before vs. after this change.
- [x] 5.2 `uv run pytest tests/executor/test_integration.py -v` (in-container, no `-m live`
      flag) — confirm `test_isolated_invocation_never_reaches_for_bare_mode` collects and passes
      unconditionally; confirm the other five are deselected the same as before.
- [x] 5.3 `openspec validate ungate-the-argv-builder-test --strict` passes.
- [x] 5.4 Commit, then archive; re-run `make check` after archiving.
