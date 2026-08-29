## Why

`tests/runtime/test_turn_integration.py::test_the_wrapper_matches_the_executor_protocol` asserts
`real_executor`'s parameter list against `runtime.turn.Executor`. The assertion is stale twice
over: it already omitted `context` (added by `carry-inherited-context-into-the-turn`) before
`give-transcripts-their-own-place` (`a3d7fdd`) added `transcripts_dir`, and nobody caught either
drift.

**Why nobody caught it: the test never ran.** The whole module carries a file-level
`pytestmark` that skips unless `claude --version` on `PATH` equals `executor.claude.
PINNED_VERSION` exactly (`2.1.225`). The installed binary is `2.1.251`. That guard is correct for
the file's other tests — they drive a real `claude` process and their claims about its behaviour
are invalid against an unpinned binary, by the same logic `PINNED_VERSION`'s own comment states
(`executor/claude.py:29`: "Behaviour is a property of the binary... A claim about what the
executor can do is invalid unless it was checked against a pinned version"). But
`test_the_wrapper_matches_the_executor_protocol` calls `inspect.signature` on a Python function.
It touches no subprocess, spends no money, and needs no particular `claude` version — it was
swept under an unrelated gate by module-level placement, and has been silently skipped for as long
as the installed binary has been ahead of the pin.

**The general shape of the defect, confirmed by checking siblings rather than assuming:**
`tests/executor/test_integration.py` carries the byte-identical guard (`shutil.which("claude") is
None or resolve_version() != PINNED_VERSION`) over its own six tests, all of which do drive a real
process. Running `pytest -q -m live -rs` on both files today shows **11 tests silently skipped**,
every one with the identical reason string
(`needs claude 2.1.225 on PATH`) — the same exact-version guard, duplicated verbatim across two
files, both currently disabled by the same point release. `pyproject.toml`'s `addopts` already
excludes `live` from `make check` on purpose (real money, real external state), so the only way
any of this shows up at all is a human running `-m live` and reading skip reasons — which is
exactly what did not happen here.

## What Changes

**1. The assertion.** Updated to the current `Executor.__call__` signature: `["frame",
"workspace", "limits", "run_id", "runs_dir", "transcripts_dir", "context", "invocation"]`.

**2. Structural fix for this specific test — decouple it from the live gate entirely.** The
module-level `pytestmark` is removed; `pytest.mark.live` plus the "claude on `PATH`" skip move
onto the five tests that actually drive a real process, individually.
`test_the_wrapper_matches_the_executor_protocol` needs no binary at all and now runs
unconditionally under `make check`, every time, on every machine. This is the one change that
makes *this* conformance test specifically unable to go stale-and-silent again: it no longer has a
gate to hide behind.

**3. The guard, in both files — silence-versus-breakage, decided explicitly (see `design.md`).**
Split the single equality check into two distinct conditions:
- `claude` absent from `PATH` → **skip**, quietly. Expected on a machine without the CLI at all.
- `claude` present but its version does not match `PINNED_VERSION` → **fail**, loudly, naming both
  versions. This is not a version range — the behavioural tests' whole premise is that
  `PINNED_VERSION` is what their assertions were checked against (same standing rule as
  `preflight`'s production guard); a version-drifted binary makes their claims unverified, not
  merely "maybe still fine." A drift the suite used to hide now stops `make test-live` cold with
  the fact stated on stdout, forcing a deliberate `PINNED_VERSION` bump (with re-verification)
  instead of an indefinite silent skip.

This is a `Requirement Fixed` in `openspec` terms only in the sense that it corrects a test; there
is no product-code change. `src/yosefactory/` is untouched.

## Non-Goals

- **`executor/claude.py`'s production `preflight()` exact-version check is untouched.** It is a
  different mechanism (a runtime canary, not a test-collection gate) and is already correct —
  `claude-executor/preflight`'s existing spec already requires it. Conflating the two was
  explicitly ruled out (see `design.md`).
- **Not weakening the pin to a minimum-version check.** Considered and rejected — see `design.md`;
  a `>=` guard would let the suite silently run behavioural assertions against an unverified
  binary, trading one silent failure mode for a subtler one.
- **`tests/board/test_reprojection.py`'s `boardlive` marker is untouched.** Different mechanism
  (network + `gh` auth, not a binary version), out of scope.
- **The general "a test that stopped running at all" detector is named, not built** (`design.md`
  — "What this does not build"). It is not cheap: no signal in this repository currently
  distinguishes "intentionally excluded" from "silently disabled," and building one would need
  either a `claude`-present CI runner (a resource this project's own constraints avoid — no
  daemon/scheduled workflow, D111) or a static audit of every `skipif` reason string, which is
  itself only as reliable as someone reading it — the exact failure this change is fixing.
- **A sixth test, `test_a_turn_that_crashes_before_commit_leaves_a_legible_gap`, is also
  binary-independent** (its own docstring: "no subprocess is ever spawned" — the `NotADirectoryError`
  fires before `real_executor` is ever called) **and is left under the live gate.** Flagged, not
  fixed here: the dispatch named the wrapper-conformance test specifically, and pulling a second
  test out changes more surface than this change's stated boundary. Reported as a separate finding.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `claude-executor/run-interface`: ADDED requirement — a check that an `Executor` implementation's
  call signature matches the protocol SHALL run unconditionally, gated on neither the live binary's
  presence nor its version.
- `claude-executor/live-test-gating` (new spec file under the existing `claude-executor`
  capability group): ADDED requirement — a live test's binary-version guard SHALL distinguish
  "binary absent" (skip) from "binary present, version drifted" (fail), so drift cannot silently
  disable behavioural coverage the way it did here.

## Impact

- `tests/runtime/test_turn_integration.py` — assertion fixed; module-level `pytestmark` replaced
  by per-test marks; the offline test moved outside the live gate.
- `tests/executor/test_integration.py` — the same absent/drifted split applied to its shared guard.
- `decisions/00NN-*.md` — the ADR: why fail-loud over minimum-version, why the offline test moves
  out rather than the gate loosening.
- `openspec/specs/claude-executor/run-interface/spec.md`,
  `openspec/specs/claude-executor/live-test-gating/spec.md` (new) — the two requirements above.
