## 1. Trace, don't assume

- [x] 1.1 Read `_workspace_lock`, `single_flight`, and both `take_turn` branches that call
      `executor(...)`; confirm the `mkdir(parents=True)` inside `single_flight` raises before
      `executor(...)` is reached in either branch.
- [x] 1.2 Confirm on this machine that `claude` is present but drifted (2.1.251 vs pinned
      2.1.225), so the test is currently excluded from `make check` for real, not hypothetically.

## 2. Ungate

- [x] 2.1 Remove `@pytest.mark.live`, `@_needs_live_claude`, and
      `@pytest.mark.usefixtures("require_pinned_claude")` from
      `test_a_turn_that_crashes_before_commit_leaves_a_legible_gap`.

## 3. Survey the remaining gated tests (record only, no fixes)

- [x] 3.1 Check each of the nine still-gated tests (six in `tests/executor/test_integration.py`,
      three in `tests/runtime/test_turn_integration.py`) for whether it actually invokes the real
      binary.
- [x] 3.2 Record the finding in `proposal.md`: `test_isolated_invocation_never_reaches_for_bare_mode`
      is a likely third binary-independent test (calls only `build_argv`, a pure function); the
      other eight genuinely drive the real process.

## 4. Spec

- [x] 4.1 `claude-executor/live-test-gating` spec delta: MODIFIED requirement — the
      never-gated-when-no-invocation rule gains a scenario for a filesystem error raised before
      any executor call (not only a pure signature check).

## 5. Verify

- [x] 5.1 `make check` — this test now included and passing where it was previously deselected.
- [x] 5.2 `uv run pytest tests/runtime/test_turn_integration.py::
      test_a_turn_that_crashes_before_commit_leaves_a_legible_gap -v` with no `-m live` flag,
      no `claude` version override — confirms it collects and runs unconditionally.
- [x] 5.3 `openspec validate ungate-the-crash-gap-test --strict` passes.
- [x] 5.4 Commit, then archive; re-run `make check` after archiving.
