## Why

`the-conformance-test-that-cannot-fail` pulled one binary-independent test
(`test_the_wrapper_matches_the_executor_protocol`) off the live gate and explicitly flagged a
second one, left in place: `tests/runtime/test_turn_integration.py::
test_a_turn_that_crashes_before_commit_leaves_a_legible_gap` still carries `@pytest.mark.live`,
`@_needs_live_claude` and `@pytest.mark.usefixtures("require_pinned_claude")`, so on this machine
(`claude` 2.1.251, pinned 2.1.225) it never runs — including under `make check`.

**Traced, not assumed.** The test points `Places.workspace` at `not_a_directory`, a plain file
(`tmp_path / "not-a-directory"`, written as text). `runtime.turn.take_turn` reaches
`with _workspace_lock(places):` in both its branches (target-is-None planning path and the normal
item path) before either calls `executor(...)`. `_workspace_lock` skips straight to
`single_flight(places.workspace_lock)` here because `places.workspace_lock != places.queue_lock`
(the test's `workspace` and `queue` are different tmp paths). `single_flight`
(`runtime/supervise.py:87`) opens with `lock_path.parent.mkdir(parents=True, exist_ok=True)`;
`lock_path` is `workspace / turn.LOCK`, so its parent *is* `not_a_directory` itself — an existing
regular file, not a directory. `Path.mkdir` on a path whose parent component is a file raises
`NotADirectoryError` immediately, inside `_workspace_lock`'s `single_flight(...)` call, which is
still executing `__enter__` — the `with` body (the `executor(...)` call) is never entered.
Confirmed by reading the call graph directly, not by trusting the test's own docstring, per
Article XII: `mkdir` runs and raises before `executor` — real or fake — is ever reached.

The claim holds. No subprocess is spawned on this test's path, so nothing about its behaviour
depends on which `claude` version (or whether any) is on `PATH`.

## What Changes

Move `test_a_turn_that_crashes_before_commit_leaves_a_legible_gap` off `pytest.mark.live`, off
`_needs_live_claude`, and off `require_pinned_claude` — same treatment
`test_the_wrapper_matches_the_executor_protocol` got. It runs unconditionally under `make check`,
on every machine, regardless of `claude`'s presence or version.

No other test in this file or `tests/executor/test_integration.py` moves. `src/yosefactory/` is
untouched — this is a test-collection-gating fix only, exactly as its predecessor was.

## Also checked: are any of the remaining gated tests binary-independent too?

Asked once, per dispatch, without expanding scope to fix anything found.

- **Six tests in `tests/executor/test_integration.py`** (`test_a_real_run_produces_a_structured_
  outcome`, `test_an_isolated_run_loads_no_host_or_repository_configuration`,
  `test_a_workspace_scoped_run_admits_repo_config_and_excludes_host_config`,
  `test_an_opted_out_run_shows_what_isolation_was_holding_back`,
  `test_a_run_that_exceeds_its_wall_clock_is_stopped_and_recorded`) call `executor.claude.run(...)`
  directly and assert on its outcome, transcript, cost, or the real agent's own init event. These
  genuinely need the binary.
- **`test_isolated_invocation_never_reaches_for_bare_mode`**, in the same file, is a likely
  seventh binary-independent test: it calls only `build_argv(...)`, a pure function building an
  argv list from an `IsolationPolicy` (`executor/claude.py:135`) — no `run()`, no subprocess, no
  version dependence. Flagged, not fixed here: fixing it touches
  `tests/executor/test_integration.py`, which is a different file than this change's stated
  boundary, and the same "ship a quietly larger version of a scoped change" hazard Article VII
  warns against.
- **Three tests in `tests/runtime/test_turn_integration.py`**
  (`test_take_turn_drives_a_real_agent_against_a_real_foreign_workspace`,
  `test_a_real_agent_reaches_done_once_the_vocabulary_is_reachable`,
  `test_two_turns_share_a_byte_identical_co_author_and_independent_run_ids`) seed a real item and
  drive `take_turn` with `real_executor` against a real workspace directory — the lock succeeds
  and the real subprocess runs. These genuinely need the binary.

So: of the nine tests still under the gate after this change, one
(`test_isolated_invocation_never_reaches_for_bare_mode`) looks like a third instance of the same
defect and is worth a future change; the other eight are correctly gated.

## Capabilities

### Modified Capabilities

- `claude-executor/live-test-gating`: MODIFIED requirement — "A test needing no real invocation is
  never gated on the binary at all" gains a second concrete scenario: a test whose failure path is
  a filesystem error raised before any executor call, not only a pure-Python signature check.

## Impact

- `tests/runtime/test_turn_integration.py` — three marks removed from one test.
- `openspec/specs/claude-executor/live-test-gating/spec.md` — one requirement's scenario set
  extended.
