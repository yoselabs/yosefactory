# ADR-0021 — a live test's version guard fails loud on drift; it does not loosen to a minimum version

**Status:** Accepted
**Date:** 2026-08-29
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a third file duplicates the same absent-vs-drifted split by hand. At that
point a shared `require_pinned_claude` helper (module or `conftest.py`) is worth the indirection;
two copies were left as-is here rather than introduced as a shared abstraction pre-emptively.

## Context

`tests/runtime/test_turn_integration.py::test_the_wrapper_matches_the_executor_protocol` asserts
`real_executor`'s parameter list against `runtime.turn.Executor`. The assertion was stale (missing
`transcripts_dir`, added by `give-transcripts-their-own-place`, `a3d7fdd`) and nobody noticed,
because the whole module — including this one offline, binary-independent test — carried a
file-level `pytestmark` skipping unless the installed `claude` matched `PINNED_VERSION`
(`2.1.225`) exactly. The installed binary is `2.1.251`. The identical guard, byte-for-byte, exists
in `tests/executor/test_integration.py` over six more tests. Verified: `pytest -m live -rs` on
both files showed 11 tests silently skipped with the identical reason string.

## Decision 1 — absent binary skips; drifted binary fails, loudly, naming both versions

Split the single `shutil.which("claude") is None or resolve_version() != PINNED_VERSION` condition
into two: a module-level `skipif` on absence only (quiet, expected — a machine with no `claude` at
all), and a `require_pinned_claude` fixture, requested explicitly by every test that drives a real
process, asserting `resolve_version() == PINNED_VERSION` and failing with both versions named if
not.

**Rejected: loosening to a minimum-version guard (`>=`).** `PINNED_VERSION`'s own comment
(`executor/claude.py`) already states the rule this decision follows rather than overturns:
behaviour is a property of the binary and moves on point releases, so a claim about what the
executor can do is invalid unless checked against the pinned version specifically.
`claude-executor/preflight`'s spec enforces the identical rule for the production canary. A `>=`
guard would let these tests' behavioural assertions — exact `Outcome` values, exact trailer
formats, exact stream shapes — run against a version this suite never verified, and a pass would
be exactly as uninformative as the silent skip it replaces: green for the wrong reason. The defect
here was never "the pin is too strict"; it was "drift is invisible." The fix targets visibility.

## Decision 2 — the offline conformance test is moved out of the live gate entirely, not just re-pinned

`test_the_wrapper_matches_the_executor_protocol` calls `inspect.signature` on a plain function. It
needs no `claude` binary, at any version, ever. Fixing only the assertion would leave it exactly as
fragile: the next point release makes it silently invisible again regardless of correctness.
Fixing only Decision 1 without relocating this test would still leave it unrun on any machine with
no `claude` installed — a `make check`-only environment, a fresh clone, this project's own
container. So the test carries neither `pytest.mark.live` nor any skip condition; it runs
unconditionally, every `make check`, every machine.

## What this does not do

- Does not touch `executor/claude.py`'s production `preflight()` — a different mechanism (runtime
  canary vs. test-collection gate), already correct, with its own spec.
- Does not build a general "a test stopped running silently" detector. No cheap mechanism
  distinguishes intentional exclusion (`live`/`boardlive`, kept out of `make check` on purpose for
  cost/external-state reasons) from silent drift without either a scheduled `claude`-present job
  (the daemon/scheduled-workflow shape D111 argues against for a single-operator repo) or a
  by-hand audit of `skipif` reasons — which only works if read, the exact failure this fixes.
  Named, not built; owed if a third instance of this pattern turns up.
- Leaves a sixth, also binary-independent test
  (`test_a_turn_that_crashes_before_commit_leaves_a_legible_gap`) under the live gate. Its own
  docstring states no subprocess is ever spawned on its path, so it shares this defect's shape; not
  pulled out here because the dispatch scoped this change to the wrapper-conformance test
  specifically. Reported separately.

## Verified

`uv run pytest -q -m live tests/runtime/test_turn_integration.py tests/executor/test_integration.py`
on this machine (`claude 2.1.251`, pinned `2.1.225`): 10 tests fail loudly at fixture setup, each
naming both versions; 1 is deselected (no longer `live`-marked) rather than silently skipped.
`make check`: 446 passed (445 before this change — the relocated test now runs under plain
`pytest`), 13 deselected (14 before).
