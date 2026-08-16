## Context

See `proposal.md` — Why, which carries the measured state. The design decisions all follow from one
structural fact: **`_finish` in `runtime/turn.py` is the only production constructor of a
`TurnRecord`**, it takes `outcome` as a positional literal, and its four call sites supply that
literal by hand. The declared mapping in `executor/outcome.py` is consulted by nobody that writes a
row.

So "give the fields their writers" is not an `executor/` change. `executor/` already holds the typed
values; `runtime/turn.py` is where they are discarded.

## Goals

- Both fields non-null on rows a real run writes, for every ending where the executor has a reason.
- One place that knows which executor ending means which turn outcome, consulted rather than mirrored.
- No new vocabulary anywhere.

## Non-Goals

- Changing what `note` is for. It stays prose and keeps the subject and the detail string.
- Making `BlockedKind.AWAITING` reachable from an executor result — it describes the reducer's path.

## Decisions

### D1 — `blocked_kind` is derived in `executor/`, beside `protocol_outcome`

The executor knows which of its endings is a denied approval and which is a refusal. A property on
`RunResult` returning `BlockedKind | None` puts that knowledge in the same class as
`protocol_outcome`, which already answers the sibling question, from the same input, one line away.

*Alternative considered:* a branch in `runtime/turn.py` mapping `RunOutcome` to `BlockedKind`.
Rejected — it is a second copy of the executor's own vocabulary living in the caller, which is what
`run-interface`'s capability-blind requirement exists to prevent. The runtime would then have to be
edited every time the executor's endings change.

### D2 — `_finish` takes the reason fields; it does not take a `RunResult`

`_finish` is called from four sites, and only two of them have a result to hand: the others are
`nothing-ready` and a supervisor-authored ending. Passing a `RunResult` would make the runtime's
record-writing helper depend on the executor's result type for the benefit of half its callers.

Two optional keyword arguments, defaulting to `None`, keep the two resultless sites unchanged and let
the record's own validation reject an inconsistent pair — which it already does, since a reason field
on the wrong outcome is a `RecordError`. **The validation written in the previous change is the
enforcement mechanism here; nothing new is needed to catch a miswired call site.**

### D3 — The non-success branch consults `protocol_outcome`, and the `failed(...)` helper narrows

Today `failed(detail)` is a closure that fixes `Outcome.FAILED` and `EnforcedBy.HARNESS`, and the
non-success branch calls it for all six non-success endings. The branch becomes: take the outcome from
`result.protocol_outcome`, take `failure_kind` and `blocked_kind` from the result, and keep `failed()`
for the cases that genuinely are harness-authored failures with no executor result behind them — a
refused proposal, a failed append, a gate that did not pass.

That split matters beyond tidiness: those remaining `failed()` calls are the ones `turn-record`'s new
requirement explicitly *permits* to assert an outcome, because no executor result stands behind them.

### D4 — `note()` is deleted rather than deprecated

No caller, in production or in tests, except one assertion whose subject is the workaround itself
(`tests/executor/test_stream.py:194`). D002 protects the ledger, not source. Leaving a shim that
formats typed values into a string is leaving the next writer a way to satisfy the old, weaker form of
the requirement this change strengthens.

*Verified against disk, because the dispatch's summary of it was two workers' reports merged:* the
sole reference is at line 194, not 141; line 141 is an isolation-leak assertion. The claim that
`note()` has no production caller is correct.

### D5 — The receipt is tiered, and two tiers turned out narrower than planned — stated, not implied

`make check` green proves the wiring compiles. It does not prove any row changed, and this is the
first change where those two are far apart. The tiers and their reachability are in the proposal.

**The plan for this section was wrong and was corrected against the real binary rather than argued
from the pinned version's changelog.** The assumption was that a turn ceiling of 1 forces `turn_limit`
and a tiny `--max-budget-usd` forces `budget_exhausted`. Neither survives contact with `build_argv`:
no flag for either is ever emitted, and `StreamReader.classify` only reaches those branches from the
**model's own** terminal event, never from the harness's supervision. A harness-forced kill — the only
ending this executor can reliably provoke — exits on `SIGTERM`, which `classify` reads as
`RunOutcome.CANCELLED` with no kind, discarding whatever reason `supervise.govern`'s own `Stop`
carried for its own separate ledger write.

**Second pass, checked rather than assumed: the wall-clock integration test cannot serve even as a
one-assertion receipt.** It calls `executor.claude.run()` directly with its own `recorder`, so its
record is written by `supervise.govern` — a writer this change never touches, entirely separate from
`_dispose`. `govern`'s wall-clock `Stop` carries no `kind` (the field defaults to `None` and nothing
sets it for that stop), so that record's `failure_kind` is `None` regardless of anything in this
change. More generally: **no existing integration test drives `runtime.turn.take_turn`**, which is
the only call path that reaches the code this change edited. Every integration test in the repo
exercises `claude.run()` in isolation.

**Conclusion, arrived at by two corrections rather than one guess:** this change ships with a wiring
receipt for both reason fields and every value in both closed sets, and **no live receipt for
anything**, because producing one would require new integration scaffolding — a real item, a real
repo, a real executor call routed through `take_turn` — which is out of this change's scope, not a
gap it quietly leaves. That scaffolding, plus wiring `--max-turns`/`--max-budget-usd` into
`executor/claude.py`, are two findings for whoever takes them next, not patches folded in here under
schedule pressure.

## Risks / Trade-offs

- **The line this change edits is the line YF-3 is editing now** → this is a genuine collision, not a
  phantom. Reported before applying; the director sequences. If YF-3 lands first, the f-string is
  already gone and this change's job at that site is smaller — it should re-read the file rather than
  apply a plan written against the old text (Article XII).
- **Endings become `blocked` that were `failed` yesterday** → a stall detector counting `failed` rows
  will see fewer, and one counting `blocked` more. Both are more correct, and no existing row changes;
  the discontinuity is a fact about the fix and belongs in the closing report.
- **`_finish` grows two parameters used by one of four callers** → accepted over the alternative in
  D2. If a third reason field ever arrives, that asymmetry is the argument for passing a small
  reason object rather than a widening signature.
- **A miswired call site fails loudly rather than silently** → this is the mitigation, not a risk:
  `TurnRecord` rejects a reason field on the wrong outcome, so the failure mode is a `RecordError` at
  write time rather than a wrong row.

## Migration Plan

None for data. Rows already written keep null fields and stay readable; `from_dict` treats a missing
key as null. The only forward-incompatibility is that a row written after this change carries values
where an older reader expected none — which that reader already tolerates, because the field was
added nullable in the previous change.
