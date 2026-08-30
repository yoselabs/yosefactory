## Context

Third instance of the same defect: a binary-independent test sitting behind the live-binary gate
because it shares a file (or, here, a module-level `pytestmark`) with tests that genuinely need
`claude`. The first two instances (`the-conformance-test-that-cannot-fail`,
`ungate-the-crash-gap-test`) each fixed one test and explicitly deferred the general question of
detection. This change fixes the third instance and is the one that owes an answer to that
question, per dispatch.

## Goals / Non-Goals

**Goals:** move exactly one test off the live gate, after confirming by call-graph trace (not
docstring, not the survey that flagged it) that `build_argv` spawns no subprocess and checks no
version. Name a candidate detector mechanism.

**Non-Goals:** no change to `PINNED_VERSION`, `preflight()`, or the absent-vs-drifted split itself.
No change to any of the other five tests in this file — traced and confirmed they genuinely drive
`executor.claude.run(...)` against a real agent. No detector mechanism built (see below for why).

## Decisions

**Trace over survey.** `ungate-the-crash-gap-test`'s survey already named this test as "a likely
seventh binary-independent test" from reading its body. Re-traced anyway, because the decorator —
not the body — is what actually gated it, and the decorator's fixture (`require_pinned_claude`)
does call `resolve_version()`, which does spawn `claude --version`. The survey was right about the
body and silent about the decorator; both needed checking, not just the one the docstring made
easy to check.

**Keep the absent-binary skip; drop only the two binary-driving marks.** The previous two
exemptions carried *no* gate at all — correct for them, because neither depends on `claude` in any
way. This test is different: `build_argv` calls `_binary()` unconditionally
(`shutil.which("claude")`, raising if absent), so it needs the binary resolvable on `PATH` even
though it never runs it. Dropping the `skipif` too would turn "claude not installed" from a skip
into an `ExecutorError`, on any machine or CI image that lacks the binary — worse than the status
quo, not better. `_needs_live_claude` (module-scoped skipif, renamed from the removed `pytestmark`
list so both files share the name) stays on this test; `pytest.mark.live` and
`require_pinned_claude` do not.

**Module-level `pytestmark` becomes per-test marks.** It applied `pytest.mark.live` uniformly to
all six tests in the file — the same shape `test_turn_integration.py` already moved away from for
the same reason (two of its five tests needed to differ from their neighbours). Converting here
makes the two files consistent and is the only way to keep five tests live-gated while un-gating
the sixth in the same module.

## The detector question, owed twice already

All three fixes were found the same way: a human read a skip reason (or, this time, a decorator)
and asked whether it was earned. That is precisely the mechanism that let the original defect
(silent version drift, `the-conformance-that-cannot-fail`'s root cause) go unnoticed for as long as
nobody ran `-m live -rs` by hand. Three instances of the same failure surfaced by the same manual
mechanism is the fleet's own standing rule (*an invariant needs a detector, or it is a comment*)
arriving with a receipt attached.

**A scheduled binary-present job is not a candidate.** `the-conformance-test-that-cannot-fail`
already rejected this shape (running a `claude`-present job on a schedule to catch drift) because
it collides with D111's no-daemon rule for a single-operator repository. Nothing here changes that
argument, so any candidate that only works by adding a cron job or a background watcher is out.

**Candidate: a static AST check over every `pytest.mark.live`-marked test, run inside plain
`make check` (never live-gated itself).** Shape: walk each test file's functions carrying
`@pytest.mark.live` (directly or via a fixture in its `usefixtures` list that transitively calls a
known binary-driving symbol — `resolve_version`, `executor.claude.run`, or `subprocess.run`/`Popen`)
and assert the function's own body (or its declared fixtures') actually references at least one of
those symbols. A `live`-marked test whose body contains none of them fails this check by name,
converting "this test stopped needing the binary" from a fact a human must notice into a fact a
plain `pytest` run states. Cheap: no subprocess, no network, one AST walk over a handful of test
files, part of `make check`'s ordinary cost.

**What it would not catch:** a test that references `resolve_version` or `run` in a helper it calls
indirectly through several layers of indirection the AST walk does not follow (mitigatable by
checking the whole call graph statically, at increasing cost and false-negative risk); a test that
imports one of those symbols but never actually reaches it at runtime (the crash-gap test's own
shape — it doesn't call `run` in its body at all, because it crashes before doing so on a mocked
path, so a naive "must call `run`" check would misclassify it as a false positive worth un-gating
when it is actually correctly *left* gated... except it isn't, it was moved. So the check needs to
walk from "gated" to "provably reaches an invocation," and the crash-gap test provably does *not*
reach one either, which is why it was moved. The check the two together suggest is really: **every
`live`-marked test must be shown, by trace, to reach a real invocation; every un-gated test must be
shown to not.** An AST walk can approximate the second half syntactically; the first half (proving
a path is *reachable*, not just referenced) is closer to abstract interpretation than a lint rule,
and is not attempted here.

**Not built in this change.** Building it correctly enough to trust needs the reachability analysis
above, which is not "genuinely small" — a naive version (grep for known symbol names in each
`live`-marked test's source) would produce both false positives (symbol referenced but on a
provably-unreached branch, as `test_a_turn_that_crashes_before_commit_leaves_a_legible_gap`'s own
sibling tests that also call `run` might exhibit under a different mock) and false negatives
(reached through a helper function, as none of the six tests here do today, but nothing prevents a
future one from doing so). Shipping a detector that itself needs a human to audit its false
positives is the same failure mode one level up. **Owed, more concretely than before**: the shape
above is specific enough to build next time a fourth instance turns up, or on its own if that
feels too long to wait — this change's scope is the one test, not the mechanism.

## Risks / Trade-offs

**Risk:** a future edit to `build_argv` adds a real invocation (e.g., a version probe inlined
instead of delegated to `resolve_version`) and this test would then need the live gate back with no
detector to say so. **Mitigation:** none built here, same posture the prior two changes took for
the same class of risk — accepted, and named as exactly the gap the detector above would close.

## What the receipt proves and does not

**Proves:** collection count for `tests/executor/test_integration.py` under plain `make check`
(no `-m live`, no `claude` version override) moves from 1 to 2 — this test now collected and
passing where it was previously deselected by `pytest.mark.live`. Confirmed in-container, where the
image ships the pinned `claude` binary, so `_needs_live_claude`'s skip does not fire either.

**Does not prove:** that `build_argv`'s output is correct against a real `claude` invocation end to
end — this test asserts only the argv list's shape, which is what it always asserted; nothing about
its own correctness changed, only whether it runs by default. It also does not prove the detector
question is closed — named, not built, per above.
