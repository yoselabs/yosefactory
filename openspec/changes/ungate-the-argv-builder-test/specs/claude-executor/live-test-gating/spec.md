## MODIFIED Requirements

### Requirement: A test needing no real invocation is never gated on the binary at all

A test whose assertions do not depend on invoking the real `claude` binary — for example, a
signature-conformance check performed with `inspect.signature`, or a test whose failure path
raises before any executor call is reached — SHALL NOT be gated on the binary's presence or
version, regardless of which file it is defined alongside.

A test that builds invocation arguments via a pure function (for example, `build_argv`) without
ever executing them is exempt from the live-cost and version gates on the same grounds, but not
necessarily from the absent-binary skip: if the argument-building function itself requires the
binary resolvable on `PATH` to construct its result (as opposed to merely referencing its name as
a string), that dependency is real and SHALL be preserved as a skip rather than dropped, even
though the version-specific and live-cost gates do not apply.

**Reason, carried with the rule:** the defect this capability exists to prevent recurring
(`the-conformance-test-that-cannot-fail`) was exactly this: an offline, binary-independent test
placed under a module-level gate meant for its neighbours, silenced by a guard that had nothing to
do with what it actually checked. The same defect recurred a second time
(`ungate-the-crash-gap-test`): a test asserting a `NotADirectoryError` raised by a lock's own
`mkdir` before any executor is invoked, gated identically to its neighbours that do drive a real
process. A third instance (`ungate-the-argv-builder-test`) showed the exemption is not always
all-or-nothing: a test can be independent of the binary's *version* and of ever *executing* it,
while still depending on the binary's mere *presence* on `PATH` — a narrower case than the first
two, which needed no gate of any kind.

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

#### Scenario: A test builds invocation arguments without invoking them, but the builder needs the binary resolvable

- **WHEN** a test's assertion is entirely about the shape of an argv list a pure function
  constructs, and that function resolves the binary's path (without executing it) as part of
  building the list
- **THEN** the test is exempt from the live-cost mark and from the version-pinned fixture
- **AND** the test still skips, quietly, when no `claude` binary is present on `PATH` at all —
  that one precondition is real and is not dropped along with the other two
