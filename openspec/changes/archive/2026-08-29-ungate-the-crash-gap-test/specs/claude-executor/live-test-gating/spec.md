## MODIFIED Requirements

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
