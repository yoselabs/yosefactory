## Why

`failure_kind` and `blocked_kind` are typed, closed, validated, drift-detected — and null on every
row a real run has ever written. Nothing writes them. Exploring for the writer found the collapse is
worse than the one already recorded, and in a different place.

**`runtime/turn.py:397` narrows every non-success executor result to `Outcome.FAILED`.**

```
declared:  RunOutcome.NEEDS_APPROVAL ─┐
           RunOutcome.REFUSED        ─┴─ _TO_PROTOCOL ──▶ Outcome.BLOCKED
live:      every non-SUCCESS ─────────── failed(f"...{result.failure_kind}...") ──▶ Outcome.FAILED
```

Three consequences, each verified against disk rather than inferred:

1. **`_TO_PROTOCOL` has no production caller.** `RunResult.protocol_outcome` is referenced only by
   two tests and `executor/claude.py:215`. `_finish` — the single production constructor of
   `TurnRecord` — takes `outcome` as a literal from its four call sites.
2. **No production path can produce `Outcome.BLOCKED` from an executor result at all.** So
   `blocked_kind` is not merely unwritten, it is unwritable: the outcome it is legal beside never
   occurs. A run stopped by a permission denial is on record today as a **failure**.
3. **This is a `claude-executor/run-interface` violation, not a gap.** That capability requires the
   mapping from the executor vocabulary to the turn outcome to be *total and declared*. It is
   declared, and then bypassed by the only caller that matters.

The typed values are already in hand at the call site: `result.outcome` and `result.failure_kind` are
typed, and the line stringifies both into a note **one line before** constructing a record that has a
typed field for each. That is the third instance of authoring-without-persisting in these two fields'
lifetime, and the first where the typed value and its typed home are in the same expression.

**No promotion id.** Dispatched by the director from this worker's own report; the entity is theirs.

## What Changes

- **`RunResult` gains `blocked_kind`**, derived from its own stop reason the way `protocol_outcome`
  already is. The executor knows which of its endings is a denial and which is a refusal; deriving it
  there keeps the runtime free of a second copy of that knowledge.
- **`_finish` takes both reason fields and passes them to the record**, and its callers stop
  stringifying typed values into `note`. `note` keeps what only prose can carry — the detail string
  and the subject — and loses what a field now holds.
- **The non-success branch consults the declared mapping** instead of asserting `FAILED`, so a denial
  and a refusal reach the record as `blocked` with a kind, and everything else as `failed` with one.
- **`RunResult.note()` is deleted.** It has no caller anywhere: the sole reference is an assertion in
  `tests/executor/test_stream.py:194` that exists to check the workaround it was. With both fields
  written, the workaround has nothing left to carry.
- **BREAKING for readers of `note`'s shape** — nothing parses it, and nothing may: it is prose. Rows
  already written are untouched and stay readable ([[D002]]).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `claude-executor/run-interface`: the total mapping becomes a requirement the record-writing path
  must *use*, and the "until a turn record can hold the kind" clause retires — the record can hold it.
- `run-guardrails/turn-record`: both reason fields acquire a stated writer, and the record's outcome
  for an executor result is required to come from the declared mapping rather than from a literal.

## Impact

- `src/yosefactory/runtime/turn.py` — the non-success branch, `_finish`'s signature, the four call
  sites. **This is the collision:** the f-string at line 397 is the one YF-3 is retiring right now.
- `src/yosefactory/executor/outcome.py` — the derivation, and `note()`'s deletion.
- `tests/executor/test_stream.py`, `tests/runtime/test_turn_cycle.py`, `tests/executor/test_integration.py`.

## Non-goals

- **Widening either vocabulary.** Both sets are closed and stay closed; this change moves values, it
  does not add any.
- **Making `awaiting` reachable.** `BlockedKind.AWAITING` describes an item that entered `blocked`,
  which is the reducer's path and not an executor result. It stays unwritten by this change, and that
  is correct rather than incomplete.
- **Bounding `needs_approval`.** Still the S172 hole declared in `turn-record`; still needs a question
  to acquire a deadline. This change makes it *recorded*, which is what a fix would first need.
- **Retiring `note` itself.** The prose field stays; only the executor's shim for it goes.

## The receipt, and what it cannot prove

The director asked for this plainly, so: **`make check` passing would prove almost nothing here.**
This is the first change whose entire purpose is to make a field non-null, which means the ordinary
green build is compatible with no real row ever changing. Three tiers, and only two are obtainable:

| Receipt | Proves | Obtainable |
|---|---|---|
| unit test through `_finish`/`_dispose` with a constructed `RunResult` | the wiring carries the value into the record | yes |
| real binary forced to a non-success ending, record read back off disk | a real run writes a non-null field | **yes, for one ending, and it is not the one this proposal first assumed** |
| real binary producing `refused`, `needs_approval`, `turn_limit`, or `budget_exhausted` | the specific kind end to end | **no** |

**Corrected during apply, and recorded here rather than silently fixed:** the design assumed a low
turn ceiling would force `TURN_LIMIT` and `--max-budget-usd` would force `BUDGET_EXHAUSTED` on demand.
Neither holds. `build_argv` never emits `--max-turns` or `--max-budget-usd` — the module's own
docstring already says wiring the cost flag is a separate change, and no flag for a turn ceiling
exists in the pinned binary at all; the ceiling is enforced by the harness killing the process with
`SIGTERM`. And a harness kill does not reach the record as `turn_limit`: `StreamReader.classify`
returns `RunOutcome.CANCELLED` for any process that exits on `SIGTERM_EXIT` with no terminal event,
discarding whatever kind the supervisor's own stop carried. `error_max_turns` and the budget subtype
are real branches in `classify`, but they fire only if the **model's own terminal event** reports
them — nothing this executor sends can request that on demand.

**Second correction, found by reading the existing test rather than assuming its record came from the
code this change touches:** the wall-clock integration test calls `executor.claude.run()` directly
with its own `recorder`, so its record is written by `supervise.govern` — a second, separate writer
that constructs and persists its own `TurnRecord` for a harness stop, entirely apart from
`runtime.turn._dispose`/`_finish`. `govern`'s wall-clock `Stop` carries no `kind` at all (`None` by
default, never set for that stop), so the existing test's record has `failure_kind: None` today and
proves nothing about the branch this change edited. Every existing integration test exercises
`claude.run()` in isolation; none drives `runtime.turn.take_turn`, which is the only call path that
reaches `_dispose`.

**So the honest conclusion is that no live receipt for this change is obtainable at reasonable cost.**
Producing one would mean building new integration scaffolding — a real repository, a real backlog
item, a real executor call, routed through `take_turn` rather than `claude.run()` — which is new test
infrastructure, not one assertion, and it would still only reach `cancelled` given the SIGTERM
collapse above. Two wrong guesses at a cheap live receipt is the signal to stop guessing rather than
try a third: **this change ships with a wiring receipt for every reason value and no live receipt at
all**, and that is stated here rather than discovered by a reader auditing rows that do not exist.
Two further findings, neither this change's to fix: `executor/claude.py` never wires `--max-turns` or
`--max-budget-usd`, and no integration test exercises `runtime.turn.take_turn` against a real
executor — the second is why the first was never caught by a receipt.
