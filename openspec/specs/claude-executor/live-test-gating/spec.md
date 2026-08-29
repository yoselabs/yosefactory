# claude-executor/live-test-gating Specification

## Purpose
Distinguishes, in the suite's own gating logic, "no `claude` binary to test against" (an ordinary
environment gap) from "a `claude` binary present but not the one these behavioural assertions were
checked against" (a fact worth stopping the run on). The single exact-version equality check this
capability replaces conflated the two: both produced an identical silent skip, and a real point-release
upgrade went unnoticed across two files and eleven tests until a build worker happened to run
`pytest -m live -rs` by hand.
## Requirements
### Requirement: A live test's gate distinguishes an absent binary from a drifted one

A test suite requiring a specific pinned version of the `claude` binary SHALL skip, quietly, when
no `claude` binary is present on `PATH` at all. It SHALL NOT skip, quietly, when a `claude` binary
is present but its reported version differs from the pinned version; that condition SHALL fail the
test, naming both the installed and the pinned version, so the discrepancy is visible on the run's
own output rather than requiring a human to read skip reasons to notice it.

**Reason, carried with the rule:** `PINNED_VERSION`'s own standing rule (`executor/claude.py`) is
that a behavioural claim is invalid unless checked against the pinned binary version — the same
principle `claude-executor/preflight`'s production canary already enforces. A version-drifted
binary makes every behavioural assertion in these tests unverified; silently skipping them hides
exactly the fact a maintainer needs to act on, and a `>=`-style minimum-version relaxation would
let those same unverified assertions execute and report green for the wrong reason. Failing loudly
converts an indefinite silent skip into a run that stops and names the drift the first time anyone
runs it.

#### Scenario: `claude` is entirely absent

- **WHEN** a live-gated test suite runs on a machine with no `claude` binary on `PATH`
- **THEN** the gated tests are skipped, with a reason naming the missing binary
- **AND** the run's exit status reflects a normal, expected skip — nothing fails

#### Scenario: `claude` is present but a different version than pinned

- **WHEN** `claude` is on `PATH` and `claude --version` reports a version other than the suite's
  pinned version
- **THEN** each test that depends on the pinned version's behaviour fails, with a message naming
  both the installed version and the pinned version
- **AND** the failure is visible in a plain run of that test selection, without requiring `-rs` or
  any other flag to surface a skip reason

#### Scenario: `claude` is present and matches the pin exactly

- **WHEN** `claude` is on `PATH` and `claude --version` reports exactly the pinned version
- **THEN** the gated tests run normally, exactly as before this capability existed

### Requirement: A test needing no real invocation is never gated on the binary at all

A test whose assertions do not depend on invoking the real `claude` binary — for example, a
signature-conformance check performed with `inspect.signature`, or a test whose failure path
raises before any executor call is reached — SHALL NOT be gated on the binary's presence or
version, regardless of which file it is defined alongside.

**Reason, carried with the rule:** the defect this capability exists to prevent recurring
(`the-conformance-test-that-cannot-fail`) was exactly this: an offline, binary-independent test
placed under a module-level gate meant for its neighbours, silenced by a guard that had nothing to
do with what it actually checked. The same defect recurred a second time
(`ungate-the-crash-gap-test`): a test asserting a `NotADirectoryError` raised by a lock's own
`mkdir` before any executor is invoked, gated identically to its neighbours that do drive a real
process.

#### Scenario: A signature-only check runs with no `claude` binary present

- **WHEN** a test asserts a callable's parameter list against a protocol, and no `claude` binary
  is on `PATH`
- **THEN** the test still runs and still asserts, rather than being skipped alongside tests that
  do need the binary

#### Scenario: A test's failure path never reaches the executor call

- **WHEN** a test's assertion is that some earlier step (a lock, a filesystem check, an argument
  validation) raises before the executor is ever invoked
- **THEN** the test still runs and still asserts, regardless of `claude`'s presence or version —
  the raise proves no invocation happens, so no invocation's preconditions apply

