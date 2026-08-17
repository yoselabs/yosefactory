## Why

Denis: *"`make check` bills real money on this machine and nothing records it."* The dispatch for
this change framed the gap as test-specific — `tmp_path` fixtures deleting the number. **That framing
was wrong, and the correction is the finding this change is actually worth, not a footnote to it.**

**Finding: this platform has never recorded what any run cost, ever — not one, test or production.**
`TurnRecord` (`protocol/turn.py`) has **no cost field at all** — checked directly against
`to_dict`/`from_dict`, not assumed, after the dispatching director asserted from memory that it
already carried one and was wrong. `RunResult.usage.total_cost_usd` is parsed from the terminal event
in `executor/claude.py::run()` and then **dropped on the floor at every call site**, including
production `take_turn` runs against the real, non-ephemeral `ledger/runs/`. The unrecoverable figure
is not an artefact of `tmp_path`; it is that there has never been anywhere for the number to go. That
means the a2web run that satisfied Denis's kill criterion last night, and every run inside yesterday's
eleven archived changes, spent real money with no durable trace of the amount. `tmp_path` deletion is
one more way to lose a number that was already unrecorded, not the cause.

`tests/executor/test_integration.py` and `tests/runtime/test_turn_integration.py` drive the real
pinned `claude` binary. Both are `skipif`-guarded on the pinned version being present — on this
machine (`2.1.225`, matches `PINNED_VERSION`, checked directly rather than trusted) it is, so a bare
`pytest -q` — and therefore a bare `make check` — runs them. It fired at least twice last night, once
killed near completion, and fired again during this change's own baseline `make check` (see Impact —
logged honestly, not concealed by the fix landing afterward).

One archived change's record cites `$1.63`; the true figure for that session is higher and, per D002,
permanently unrecoverable now. That specific number stays lost. What this change stops is every
number after it being lost the same way.

**Two decisions, argued, not assumed:**

**1. Should `make check` fire live receipts?** Two real costs pull opposite ways. Receipts nobody runs
rot silently — this repo lost a day to exactly that shape of failure when the platform's central
transition turned out unreachable and every check was talking to fakes. But a default that spends
money on every lint-and-typecheck loop already misfired twice in one night, once mid-run. The
resolution here is **opt-in via a separate target**, not opt-out-by-recording-only: recording alone
still lets every `make check` spend, repeatedly, over a dev-loop session — the "twice in one night"
failure mode is about *frequency*, not just about invisibility, and only removing live tests from the
default path fixes frequency. The receipt-rot risk is answered structurally by keeping the live target
one command away (`make test-live`) rather than by making it hard to reach, and by requiring an
explicit target to exist and be documented, so it is not a receipt that quietly stops running.

**2. Where does the spend go?** Not `ledger/runs/`'s `TurnRecord` — that is protocol/L1, the frozen,
small, comparable-months-later shape (`CLAUDE.md`'s structural rule), and it is keyed to a backlog
item and an owner; a test invocation has neither. Forcing test spend through it means two facts in one
field, the exact shape this codebase keeps rejecting elsewhere. Instead: a small, separate,
append-only ledger — `ledger/spend.jsonl` — written from the one place both call paths already
converge, `executor/claude.py::run()`.

- **Joins to the run record.** Every row carries `run_id`, the same id `run()` already receives and
  the same id every `TurnRecord` in `ledger/runs/` is named for. Without it a spend row is an orphan
  number; with it, a reader can ask *what did this specific turn cost*, not only *what did today
  cost* — the join is what makes this an accounting artefact rather than a pile of numbers.
- **Path resolution is a second instance of a known limitation, not a fresh choice.** `SPEND_LOG` is
  resolved by walking up from `Path(__file__)`, exactly the pattern `protocol/backlog.py`'s
  `VOCABULARY_SPEC` already uses, for the same reason: a caller-supplied `runs_dir`/workspace may be
  ephemeral or foreign, and this file's own location is not. That pattern is a recorded open item —
  it resolves correctly in a dev checkout and breaks silently if yosefactory is ever installed apart
  from its own source tree, which cross-repo operation makes plausible. There are now two call sites
  with this limitation. Whoever fixes it should fix both, rather than finding the second one by
  surprise.
- **Whose ledger this is.** Under cross-repo operation, `run()` executes against a foreign workspace
  (e.g. `a2web`) while `spend.jsonl` resolves into yosefactory's own checkout regardless. That is a
  decision, not an accident: spend belongs to the platform that paid for the call, not to the
  repository the call happened to be working on.

One row per real invocation, test and production alike, because "what did today cost" does not care
who paid.

## What Changes

- **New capability** `claude-executor/spend-ledger`: `executor/claude.py::run()` appends one row to
  `ledger/spend.jsonl` after every completed invocation, at a fixed path independent of the caller's
  `runs_dir` — so it survives `tmp_path` teardown.
- **Gating**: a `live` pytest marker on both integration files; `pyproject.toml` `addopts` excludes it
  by default (`-m "not live"`); a new `make test-live` target runs `pytest -q -m live` explicitly.
  `make check` / `make test` no longer reach the live binary at all.
- **Says what it spent**: `make test-live` prints the session's total spend (summed from the new
  ledger) at the end of the run, via a `pytest_sessionfinish` hook scoped to when live tests ran.

## Capabilities

### New Capabilities

- `claude-executor/spend-ledger`: every real invocation of the pinned binary appends a durable,
  append-only row (`run_id`, `total_cost_usd`, timestamp) to `ledger/spend.jsonl`, regardless of
  whether the caller's own workspace is ephemeral.

### Modified Capabilities

None. This does not change what a run does or how it is classified — only what survives after it.

## Impact

- `src/yosefactory/runtime/spend.py` — new module: `record()`, `total_since()`.
- `src/yosefactory/executor/claude.py` — one call to `spend.record()` in `run()`.
- `pyproject.toml` — `markers`, `addopts`.
- `tests/executor/test_integration.py`, `tests/runtime/test_turn_integration.py` — add
  `pytest.mark.live` to the existing `pytestmark`.
- `tests/conftest.py` — new, session-total print hook.
- `Makefile` — `test-live` target, comment on `check`/`test` noting the split.
- `ledger/spend.jsonl` — new durable file, append-only, never deleted (D002).
- **Honest disclosure:** this change's own baseline `make check` (run before gating existed, to
  record a before/after) fired the full live suite for real — the exact accidental-spend failure
  this change exists to prevent. The amount is unrecorded, because the recorder did not exist yet
  when it happened, and is therefore an instance of the finding above, not exempt from it.

## Non-goals

- **Enforcing a spend cap.** `claude-executor/cost-ceiling` already exists for per-turn capping;
  this change is about recording, not limiting.
- **Backfilling past sessions' spend.** The $1.63 / unknowable-true-figure case stays unknowable —
  D002 forbids rewriting history, and there is nothing to recover it from.
- **Routing test spend through `TurnRecord`/`ledger/runs/`.** Argued above; a separate, smaller
  ledger fits the structural rule better than widening the frozen protocol type.
- **CI wiring for `make test-live`.** Not asked for; this is a local, opt-in target.

## The receipt question (Article XVI)

**What would distinguish built from works:** after any live run — `make test-live` or a real
`take_turn` in production — `ledger/spend.jsonl` gains one line with a real dollar figure, and
`make test-live`'s own output states the session total. `tail -1 ledger/spend.jsonl` or grepping by
date answers "what did today cost" without reading any test code. Verified in this proposal against
one already-necessary canary run (logged below), not against a re-fire of the full live suite.
