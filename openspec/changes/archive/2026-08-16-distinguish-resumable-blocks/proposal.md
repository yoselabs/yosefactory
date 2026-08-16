## Why

A turn record that reads `outcome: blocked` does not say whether anything can arrive that unblocks
it. Three different facts narrow to that one word today:

| What happened | Resumable by something arriving? |
|---|---|
| the item entered `blocked`, awaiting a question, a request or another item | yes, and bounded by a deadline |
| the agent was denied a tool it asked for (`needs_approval`) | yes, but nothing bounds the wait |
| the agent declined the work (`refused`) | **no.** Nothing arrives that changes it |

A planner reading the record cannot tell *wait* from *this will never move*, and neither can a stall
detector. The distinction survives today only inside `RunResult.note()` as free text, which is the
same degraded position `failure_kind` was in before `ffa487d` — and free text cannot be queried.

**No promotion id.** This came from the director using the state model rather than from a K160
entity; the entity is the director's to write, and this change supplies the content for it.

## What Changes

- `TurnRecord` gains **`blocked_kind`**, a sibling field to `failure_kind`, drawn from a closed set
  of three values: `awaiting`, `needs_approval`, `refused`. Absent or null unless
  `outcome` is `blocked`, rejected at write time otherwise — the same rule `failure_kind` carries.
- Resumability becomes a **derived predicate over the kind**, defined once in `protocol/`, so the
  planner and the stall detector cannot disagree about which blocks are dead ends.
- The turn-record spec declares, out loud, that **two of the three kinds have no automatic
  closure** (S172). `refused` is a dead end by design — nothing arriving changes a refusal, and the
  response is a human re-deciding, which is [[D019]]'s falsify-and-succeed rather than a resumption.
  `needs_approval` is a dead end by omission: resumable in principle, unbounded in practice, because
  a permission denial writes no question and so acquires no deadline and nothing sweeps it.
  **The field makes an existing S172 violation visible rather than creating one.** It was unbounded
  before this change; what changes is that a reader can now see it.
- A read-only drift test asserts every `RunOutcome` that narrows to `blocked` has a `blocked_kind`
  to land on, so a new executor stop reason cannot quietly reopen the collapse.

Not in this change, and named so the boundary is explicit: **the two mapping sites that would
populate the field** (`executor/outcome.py`, `runtime/turn.py`) belong to other workers. This change
makes the field recordable; a follow-up dispatch makes it recorded. Same sequencing as
`failure_kind`, whose `RunResult.note()` workaround is still retirable by whoever owns `executor/`.

## Capabilities

### New Capabilities

None. The record already exists; one field is added to it.

### Modified Capabilities

- `run-guardrails/turn-record`: one ADDED requirement — why a turn is blocked is a second axis over
  the frozen outcome, with resumability derived from it and the unbounded kinds declared.

## Impact

- `src/yosefactory/protocol/turn.py` — the enum, the field, its validation, its serialisation, and
  the resumability predicate.
- `tests/protocol/test_turn.py` — the field's rules, and the drift test that imports
  `executor.outcome` read-only.
- `openspec/specs/run-guardrails/turn-record/spec.md` — via the delta.
- **Untouched, deliberately:** `executor/`, `runtime/`. The four-value `Outcome` is not widened, no
  item state is added, and no existing record becomes unreadable — a record written before this
  change reads back with `blocked_kind: None`.

## Non-goals

- **Widening `Outcome`.** It is exactly four values and frozen; every row ever written is compared
  against every other row.
- **New item states.** `needs_approval` and `refused` are facts about an executor invocation, not
  places an item sits. A state needs a writer, and nothing would write these.
- **A `resumable` boolean on the record.** The consequence is derived from the reason; storing both
  is two representations of one fact.
- **Populating the field.** Two files in two other workers' scope. Reported, not taken.
- **Bounding `needs_approval`.** Giving a permission denial a deadline means writing a question,
  which is runtime work outside this change. Declared as a defect here; fixed elsewhere.
