## Context

Flagged by a build worker mid-`give-transcripts-their-own-place` (K D034) as an out-of-scope
finding, routed here by Denis. Verified directly rather than assumed:

```
$ PREK_ALLOW_NO_CONFIG=1 uv run pytest -q -m live -rs tests/runtime/test_turn_integration.py tests/executor/test_integration.py
sssssssssss
SKIPPED [1] tests/runtime/test_turn_integration.py:198: needs claude 2.1.225 on PATH
SKIPPED [1] tests/runtime/test_turn_integration.py:241: needs claude 2.1.225 on PATH
SKIPPED [1] tests/runtime/test_turn_integration.py:285: needs claude 2.1.225 on PATH
SKIPPED [1] tests/runtime/test_turn_integration.py:329: needs claude 2.1.225 on PATH
SKIPPED [1] tests/runtime/test_turn_integration.py:374: needs claude 2.1.225 on PATH
SKIPPED [1] tests/executor/test_integration.py:46: needs claude 2.1.225 on PATH
SKIPPED [1] tests/executor/test_integration.py:80: needs claude 2.1.225 on PATH
SKIPPED [1] tests/executor/test_integration.py:116: needs claude 2.1.225 on PATH
SKIPPED [1] tests/executor/test_integration.py:143: needs claude 2.1.225 on PATH
SKIPPED [1] tests/executor/test_integration.py:166: needs claude 2.1.225 on PATH
SKIPPED [1] tests/executor/test_integration.py:196: needs claude 2.1.225 on PATH
11 skipped in 0.16s
```

`claude --version` on this machine: `2.1.251`. `PINNED_VERSION` (`executor/claude.py:29`):
`2.1.225`. Eleven tests, two files, one guard, one point release apart.

## Decision 1 — fail loud on drift, do not loosen to a minimum-version guard

**Considered:** change `resolve_version() != PINNED_VERSION` to `resolve_version() <
PINNED_VERSION` (parsed as a tuple, since string comparison breaks on `2.1.9` vs `2.1.10`), so an
upgrade keeps the tests running instead of skipping them.

**Rejected.** `PINNED_VERSION`'s own comment states the standing rule this repository already
lives by: *"Behaviour is a property of the binary, not of this adapter, and it moves on point
releases. A claim about what the executor can do is invalid unless it was checked against a pinned
version."* `claude-executor/preflight`'s spec says the same thing about the production canary,
word for word in effect: a receipt taken against a different binary is not this receipt. The tests
this guard protects (`test_take_turn_drives_a_real_agent...`,
`test_a_real_agent_reaches_done_once_the_vocabulary_is_reachable`, the trailer-identity test, and
all six of `test_integration.py`) assert specific behavioural claims — exact `Outcome` values,
specific trailer formats, specific stream shapes — against a real binary. A `>=` guard would let
those assertions run against a binary version this suite has never verified, and a pass would be
exactly as uninformative as a silent skip: green for the wrong reason. That is a subtler version of
the same defect this change exists to fix, not a fix for it.

**What actually failed here was not "the pin is exact," it was "drift is invisible."** So the fix
targets visibility, not exactness: split "binary absent" (an ordinary, expected environment gap —
skip) from "binary present, version different from pinned" (a fact worth stopping on — fail, by
name). A developer who runs `make test-live` today, on this machine, will now see:

```
FAILED tests/executor/test_integration.py::... - AssertionError: claude on PATH is 2.1.251,
tests are pinned to 2.1.225 -- bump PINNED_VERSION (and re-verify behaviour) rather than let
this drift silently
```

instead of a quiet `11 skipped`. The fix converts a fact that required deliberately reading
`-rs` output to notice into one that stops the run and names both versions on stdout.

**Mechanism, deliberately plain:** a fixture, not module-scoped magic. Each behaviour-driving test
requests `require_pinned_claude` explicitly:

```python
@pytest.fixture
def require_pinned_claude() -> None:
    installed = resolve_version()
    assert installed == PINNED_VERSION, (
        f"claude on PATH is {installed}, tests are pinned to {PINNED_VERSION} -- "
        "bump PINNED_VERSION (and re-verify behaviour) rather than let this drift silently"
    )
```

A plain `assert` inside a requested fixture, not `pytest.fail()` at collection time and not an
autouse fixture — collection-time failure would poison the *whole module*, including the one test
(Decision 2) that must keep running when `claude` is absent or drifted; autouse would silently
re-couple every test in the file to the gate this change is removing for one of them.

## Decision 2 — the conformance test moves out of the live gate structurally, not just via a
version fix

**The deeper defect is placement, not arithmetic.** `test_the_wrapper_matches_the_executor_
protocol` calls `inspect.signature` on a plain Python function. It spends no money, spawns no
process, and its correctness does not depend on which `claude` version (if any) is installed. It
was gated behind `pytest.mark.live` + the version `skipif` purely because it lives in the same
*file* as five tests that do need a real binary, and the guard was written as a module-level
`pytestmark` — the cheapest thing to type, and the thing that silently swept an unrelated test
along with it.

Fixing only the assertion (bringing the parameter list back in step) without also fixing the
placement would leave the test exactly as fragile as it was: the next point-release bump makes it
invisible again, assertion correct or not. Fixing only the guard (Decision 1) without moving this
test would still leave it skipped on any machine with no `claude` installed at all — a `make
check`-only environment (this project's own container, CI-shaped machines, a fresh clone) would
still never run it, for a test that needs nothing from the binary to run.

**So both: the assertion is corrected, and the test is pulled off the `pytestmark` list entirely**
— no `pytest.mark.live`, no skip condition, runs on every `make check`, every machine, no
`claude` required. This is the specific, narrow fix that makes *this* test in particular
structurally unable to repeat the defect: it no longer has a gate that can drift out from under
it, because it has no gate.

## What this does not do

- **Does not touch `executor/claude.py`.** `preflight()`'s own exact-version check is production
  code with its own spec (`claude-executor/preflight`) and its own already-correct reasoning; nothing
  here contradicts or duplicates it.
- **Does not build a general "a test stopped running" detector.** Considered — the corpus's own
  standing rule is *an invariant needs a detector, or it is a comment* — but named rather than
  built: no cheap mechanism exists to distinguish "this skip is intentional" (the `boardlive`/`live`
  markers, deliberately excluded from `make check` for cost/external-state reasons) from
  "this skip is silent drift" (this defect) without either running a `claude`-present job on a
  schedule (which is exactly the daemon/scheduled-workflow shape D111 and the board-live ADR both
  argue against for a single-operator repository) or auditing `skipif` reason strings by hand,
  which only works if a human reads it — the precise failure that produced this change. **Owed,**
  not built: if a third instance of this pattern turns up, that is the signal a real mechanism is
  worth the cost.
- **Does not pull the sixth binary-independent test
  (`test_a_turn_that_crashes_before_commit_leaves_a_legible_gap`) out of the gate.** Flagged as a
  separate, smaller, out-of-scope finding rather than folded in — see `proposal.md` Non-Goals.

## Risk / what the receipt proves and does not

**What it proves:** `uv run pytest -q -m live -rs tests/runtime/test_turn_integration.py
tests/executor/test_integration.py` on this machine (installed `claude 2.1.251`, pinned
`2.1.225`) after this change shows the wrapper-conformance test collected and passing under plain
`make check` (no `-m live` needed), and the ten genuinely behavioural tests failing loudly by name
rather than skipping silently.

**What it does not prove:** that the assertion is *itself* correct against a `claude` binary at
the pinned version — this machine cannot run that binary, so the ten behavioural tests are not
executed end-to-end here, loud failure or not. The parameter-list fix is checked against the
`Executor` protocol's own source (`runtime/turn.py`) and against `real_executor`'s own signature,
both static, both read directly rather than inferred — that is a real receipt for the one test this
change repairs, not a claim about the other ten.
