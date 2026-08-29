## MODIFIED Requirements

### Requirement: One bounded call is the whole caller-facing surface

An executor SHALL expose a single operation that takes the work's frame, the working tree it
may edit, and the limits it must respect, and returns a structured result describing what the
invocation amounted to.

The operation SHALL be bounded: it returns, or the run is stopped and it returns anyway. It
SHALL NOT require the caller to poll, resume, or reconnect to a run it started.

A check that a given callable's signature matches this requirement SHALL run unconditionally —
gated on neither the real agent binary's presence on `PATH` nor its version. Such a check
inspects a Python callable's signature; it performs no invocation and asserts nothing about the
binary's behaviour, so gating it behind a live-binary guard only hides a real drift in the
signature itself.

**Reason, carried with the rule:** `test_the_wrapper_matches_the_executor_protocol` was gated
behind the same version-pinned `skipif` as the tests that do drive a real binary, purely because
it lived in the same file. The assertion went stale across two changes (`context`, then
`transcripts_dir`) and nobody noticed, because the gate that made sense for its neighbours also
silenced it. A protocol-conformance check has nothing in common with a behavioural receipt against
a real binary; conflating their gating conflates their risk.

#### Scenario: A run returns a structured result rather than output
- **WHEN** a caller invokes an executor with a frame, a working tree and limits
- **THEN** it receives a result carrying an outcome, usage, the transcript location, and whether the tree was left dirty

#### Scenario: A stopped run still returns
- **WHEN** a run is stopped because it exceeded a limit
- **THEN** the call returns a result rather than raising or hanging

#### Scenario: The protocol-conformance check runs with no `claude` binary present
- **WHEN** `make check` (or plain `pytest`, with no `-m live`) runs on a machine with no `claude`
  binary on `PATH` at all
- **THEN** the check that a wrapper's call signature matches `Executor.__call__` still runs and
  still asserts, rather than being skipped

#### Scenario: The protocol-conformance check runs on a machine whose installed `claude` has
drifted from the pin
- **WHEN** `claude` is present on `PATH` but `claude --version` reports something other than
  `PINNED_VERSION`
- **THEN** the signature-conformance check still runs (it is not gated on the binary's version at
  all), independent of whichever tests in the same file *are* gated on it
