## Why

`the-conformance-test-that-cannot-fail` and `ungate-the-crash-gap-test` each moved one
binary-independent test off the live gate. The second change's proposal.md flagged a likely third
instance, out of its own file boundary: `tests/executor/test_integration.py::
test_isolated_invocation_never_reaches_for_bare_mode` calls only `build_argv(...)`, a pure function
that returns an argv list — no `run()`, no `subprocess`, no version dependence. Recorded, not
fixed, at the time.

**Traced, not assumed (Article XII):** `build_argv` (`executor/claude.py:135`) does
`argv = [_binary(), "-p", prompt, ...]`. `_binary()` is `shutil.which("claude")`, raising
`ExecutorError` if not found — a PATH lookup, not an invocation. `build_argv` never calls
`subprocess.run` and never calls `resolve_version()` (the version check `require_pinned_claude`
performs). The test's own decorator, though, was `@pytest.mark.usefixtures("require_pinned_claude")`
— that fixture itself calls `resolve_version()`, which does `subprocess.run(["claude",
"--version"])`. So *as gated*, this test drove the real binary once per run, via the fixture, even
though its own body never did. The claim holds for the test's body; it did not hold for the test as
decorated until this change removes that fixture request.

## What Changes

Move `test_isolated_invocation_never_reaches_for_bare_mode` off `pytest.mark.live` and off
`require_pinned_claude` — same treatment the previous two tests got. Converts the module-level
`pytestmark` in `tests/executor/test_integration.py` (which applied `pytest.mark.live` to all six
tests indiscriminately) into per-test marks, matching the pattern already used in
`tests/runtime/test_turn_integration.py`, so this one test can differ from its five neighbours.

**One thing this test keeps that the previous two exemptions dropped entirely: the absent-binary
skip.** `build_argv` calls `_binary()` unconditionally, which raises if `claude` is not resolvable
on `PATH` at all — unlike `test_the_wrapper_matches_the_executor_protocol` (pure `inspect.signature`,
no PATH dependency) or `test_a_turn_that_crashes_before_commit_leaves_a_legible_gap` (crashes on a
filesystem error before any binary-related call). This test needs `claude` present, though never
executed, so it keeps `_needs_live_claude` (the absent-binary `skipif`) and loses only the two
marks tied to actually running or version-checking the binary (`pytest.mark.live`,
`require_pinned_claude`).

No other test in this file moves. `src/yosefactory/` is untouched — a test-collection-gating fix
only, exactly as both predecessors were.

## Capabilities

### Modified Capabilities

- `claude-executor/live-test-gating`: MODIFIED requirement — "A test needing no real invocation is
  never gated on the binary at all" gains a third scenario: a test that builds invocation arguments
  via a pure function that itself requires the binary resolvable on `PATH` (though never invoked)
  is exempted from the live/version gates but not from the absent-binary skip — a narrower
  exemption than the prior two scenarios describe.

## Impact

- `tests/executor/test_integration.py` — module-level `pytestmark` replaced by per-test marks; one
  test loses two of its three marks.
- `openspec/specs/claude-executor/live-test-gating/spec.md` — one requirement's scenario set
  extended.

## The detector question this is the third instance of

All three fixes were found by a human reading skip reasons — the exact mechanism that let the
underlying defect (silent version drift, `the-conformance-that-cannot-fail`'s root cause) persist
in the first place. See `design.md` for a candidate static-property mechanism, named but not built
here.
