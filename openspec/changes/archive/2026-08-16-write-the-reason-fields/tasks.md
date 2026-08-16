## 1. Re-acquire, because the target line is contested

- [x] 1.1 Re-read `src/yosefactory/runtime/turn.py` from disk. YF-3 is editing line 397; this plan was written against text that may no longer exist (Article XII)
- [x] 1.2 Re-read `src/yosefactory/executor/outcome.py` and confirm `_TO_PROTOCOL` still maps `NEEDS_APPROVAL` and `REFUSED` to `BLOCKED`, and that `protocol_outcome` still has no production caller
- [x] 1.3 Record the `make check` baseline and `git status --porcelain` before any edit
- [x] 1.4 YF-3 (`73738cf`) retired the f-string and gave `failure_kind` a writer for the run-level stops. What was left for this change, verified by re-reading the file: `_finish` still had no `blocked_kind` parameter, and every non-success executor result — including `needs_approval`/`refused` — still went through the `failed(...)` closure unconditionally, so `Outcome.BLOCKED` remained unreachable from an executor result. Shrunk to exactly that (Article VII)

## 2. The executor's half

- [x] 2.1 Add `RunResult.blocked_kind` returning `BlockedKind | None`, derived from `outcome` beside `protocol_outcome`, with a docstring stating why the derivation is here and not in the caller
- [x] 2.2 Delete `RunResult.note()` and the assertion at `tests/executor/test_stream.py:194` that was its only reference
- [x] 2.3 Assert the two derivations agree: every ending whose `protocol_outcome` is `BLOCKED` has a non-null `blocked_kind`, and every other ending has a null one — a total mapping checked as total

## 3. The runtime's half

- [x] 3.1 Give `_finish` optional `failure_kind` and `blocked_kind` keyword arguments defaulting to `None`, passed straight to `TurnRecord`
- [x] 3.2 Rewrite the non-success branch to take its outcome from `result.protocol_outcome` and both reasons from the result, instead of calling `failed(...)`
- [x] 3.3 Leave the remaining `failed(...)` calls alone — a refused proposal, a failed append, a gate that did not pass are harness-authored with no executor result behind them, which the new requirement permits
- [x] 3.4 Reduce the note at that site to what only prose carries: the subject and the detail. No stringified enum values

## 4. Tests — the wiring tier

- [x] 4.1 A result that failed with a typed reason produces a record whose `failure_kind` is that reason
- [x] 4.2 A denied approval produces `outcome: blocked` with `blocked_kind: needs_approval`, and is **not** `failed` — the assertion that would have caught the live defect
- [x] 4.3 A refusal produces `outcome: blocked` with `blocked_kind: refused`
- [x] 4.4 The note at that site no longer contains any enum value, so nothing can start parsing it again
- [x] 4.5 A supervisor-authored kill still writes null reasons, and `enforced_by` still names the author

## 5. The live tier: two corrections, then a stated conclusion rather than a third guess

- [x] 5.1 First guess wrong, checked before writing anything: no flag exists to force `turn_limit` or `budget_exhausted` on demand, and a harness-forced kill reaches `claude.run()`'s `RunResult` as `cancelled`, discarding whatever kind `supervise.govern`'s own `Stop` carried
- [x] 5.2 Second guess wrong, checked before writing an assertion that would have failed: the existing wall-clock integration test's record is written by `supervise.govern` directly (its own `recorder.write`), never by `_dispose` — a wall-clock `Stop` carries no kind at all, and no existing integration test drives `runtime.turn.take_turn`, the only path that reaches the code this change edited
- [x] 5.3 Conclusion recorded in `proposal.md`/`design.md` rather than a third guess executed against real API cost: **no live receipt is obtainable within this change's scope.** Wiring tier only, stated as such
- [x] 5.4 Do **not** attempt a live `refused`, `needs_approval`, `turn_limit`, or `budget_exhausted` — none is provocable from this executor as it stands, and building the scaffolding to even attempt one is out of scope
- [x] 5.5 Report two findings for their owners, not fixed here: `executor/claude.py` never wires `--max-turns`/`--max-budget-usd`; no integration test exercises `runtime.turn.take_turn` against a real executor, which is why the first finding was never caught

## 6. Close

- [x] 6.1 `make check` green against the 1.3 baseline, and the count difference attributed — other workers are landing in this window
- [x] 6.2 `openspec validate write-the-reason-fields --strict` passes **before** archiving (Article XIV)
- [x] 6.3 One commit, `git commit -F <file> -- <literal paths>`, `PREK_ALLOW_NO_CONFIG=1`, then `git diff --cached` confirmed empty — never trust `||` behind a pipe
- [x] 6.4 Archive, then check `git diff --numstat -- openspec/specs/`: deletions only inside blocks this change declared MODIFIED, and named in the commit message
- [x] 6.5 Report: which fields are now non-null on a real row and which are not, in those words. A wiring receipt is not a live receipt and the report must not blur them

## Outcome

**Landed as `2981414`.** Baseline `make check` was 235 passed at `f5815c2`; after this commit, 238.
Index empty after the commit.

**What is non-null on a real row now, and what is not, stated in those words:**

- `failure_kind` — was already writable for the run-level stops (YF-3's `73738cf`), unaffected here.
- `blocked_kind` — **newly writable and newly written.** `needs_approval` and `refused` now reach
  `_finish` as `Outcome.BLOCKED` with the matching kind, wired through `_dispose`'s new `blocked(...)`
  closure. Every unit test through `_dispose`/`_finish` with a constructed `RunResult` confirms the
  value reaches a `TurnRecord`. **No row from a real run has been observed carrying it**, and none
  could be produced at reasonable cost — see below.

**The live-receipt tier was planned wrong twice, and both corrections are on record rather than
absorbed silently:**

1. First plan assumed a low turn ceiling would force `turn_limit` and a small `--max-budget-usd`
   would force `budget_exhausted`. Checked against `build_argv` before writing any test: neither flag
   is ever sent, and a harness-forced kill reaches `claude.run()`'s `RunResult` as
   `RunOutcome.CANCELLED`, discarding whatever kind `supervise.govern`'s own `Stop` carried for its
   separate ledger write.
2. Second plan assumed the existing wall-clock integration test could be extended with one assertion
   at no extra cost. Checked before writing it: that test's record is written by `supervise.govern`
   directly, a writer this change never touches, and a wall-clock `Stop` carries no kind at all — the
   assertion would have asserted nothing about this change and would likely have failed against `None`.

**Conclusion:** this change ships a wiring receipt for `blocked_kind` and no live receipt, stated here
rather than left for a reader auditing rows that were never produced. Two findings follow from the
same investigation, neither taken: `executor/claude.py` never wires `--max-turns`/`--max-budget-usd`
despite `NATIVE` naming the cost flag as measured; and no integration test in the repo drives
`runtime.turn.take_turn` against a real executor, which is why the first finding was never caught by
a receipt.

**Left, deliberately:** the two findings above, and `runtime.turn._dispose`'s remaining `failed(...)`
calls for the resultless cases (refused proposal, failed append, gate that did not pass) — permitted
by the new `turn-record` requirement and untouched by design.
