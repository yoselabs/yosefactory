## Context

`the-conformance-test-that-cannot-fail` (`decisions/0021-fail-loud-on-claude-version-drift-not-
a-minimum-version-guard.md`) already decided the general shape: a live-binary gate exists to
protect claims that were only ever checked against a pinned `claude` version, and a test whose
assertion does not depend on the binary at all should never sit behind that gate regardless of
which file it lives in. That decision moved one such test
(`test_the_wrapper_matches_the_executor_protocol`) and explicitly named a second
(`test_a_turn_that_crashes_before_commit_leaves_a_legible_gap`) as out of scope for that change,
to be handled separately. This is that separate change — no new decision, an application of the
existing one to a second instance, confirmed by tracing the call path rather than trusting the
test's own docstring (Article XII).

## Goals / Non-Goals

**Goals:** move exactly one test off the live gate, after confirming by call-graph trace (not
docstring) that no subprocess is ever spawned on its path.

**Non-Goals:** no change to `PINNED_VERSION`, `require_pinned_claude`, or the absent-vs-drifted
split itself (`claude-executor/live-test-gating`'s first requirement, untouched). No fix to
`test_isolated_invocation_never_reaches_for_bare_mode`, flagged as a likely third instance in
`proposal.md` but out of this change's file boundary (`tests/executor/test_integration.py`).

## Decisions

**Trace over docstring.** The test's own docstring already claimed "no subprocess is ever
spawned." Accepting that at face value would repeat exactly the failure mode Article XII exists
to prevent — a comment asserting behavior nobody re-checked as the code around it moved. Traced
instead: `_workspace_lock` → `single_flight` → `mkdir(parents=True)` on a path whose parent is a
plain file, confirmed to raise before either of `take_turn`'s two `executor(...)` call sites.

**No new ADR.** `decisions/0021` already covers the general rule this change applies; writing a
second ADR for the same rule's second application would duplicate rather than extend it.

## Risks / Trade-offs

**Risk:** a future refactor of `_workspace_lock` or `single_flight` changes the raise site so this
test's crash happens *after* an executor call, silently reintroducing a binary dependency with no
gate to catch it. **Mitigation:** none built here (would need a "does the mocked path also crash
before any executor call" static check, which does not exist) — accepted, same posture the prior
change took for the same class of risk.
