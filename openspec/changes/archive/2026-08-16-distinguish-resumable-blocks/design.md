## Context

See `proposal.md` — Why. Two facts about the current code decide most of this design:

1. `Outcome.BLOCKED` is written from **two** places, in two packages neither of which this change may
   touch: `executor/outcome.py` narrows `RunOutcome.NEEDS_APPROVAL` and `RunOutcome.REFUSED` to it,
   and `executor/stream.py:outcome_for` narrows the item state `blocked` to it.
2. `protocol/turn.py` already carries the answer's shape. `failure_kind` was added in `ffa487d` as a
   nullable sibling to `outcome`, valid only for one outcome value, drawn from a closed executor-facing
   set. This change is the second instance of that pattern, not a new one.

Ownership: `protocol/` is this worker's; `executor/` and `runtime/` are not (Article IV).

## Goals

- One typed field and one derived predicate, both in `protocol/`.
- Every record ever written stays readable and comparable — the field is additive and nullable.
- A drift detector, so a new executor stop reason that narrows to `blocked` cannot silently reopen
  the collapse the way `version_mismatch` nearly did for `failure_kind`.

## Non-Goals (design level; scope-level ones are in the proposal)

- No change to how `blocked` is *decided*. This records why, it does not re-route anything.
- No consumer. The predicate is defined here; the stall detector that reads it is not built here.

## Decisions

### D1 — A sibling field, not a fifth outcome

`Outcome` is four values and frozen because every row ever written is compared against every other
row. A fifth value would make every historical `blocked` row ambiguous rather than merely
uninformative: a reader could no longer tell whether an old `blocked` was a wait or a refusal, and
would have to know the field's introduction date to interpret it. A nullable sibling leaves old rows
saying exactly what they said before — blocked, reason not given.

*Alternative considered:* fifth value `refused`. Rejected on the compatibility argument above, and
because it splits *did it advance* across two questions.

### D2 — Three values, with `awaiting` explicit rather than implied by null

The tempting shape is two values — `needs_approval`, `refused` — with null meaning "the ordinary item
block". Rejected: null would then carry two meanings at once, "an item block" and "no reason given",
and a reader could not separate them. Null keeps exactly the meaning it has on `failure_kind`: the
writer had no typed reason to give.

`awaiting` is also the right *name*: it points at the item's `awaiting` object, where the block's
`kind`, `ref`, deadline and policy already live. The value says "the detail is over there" rather
than duplicating any of it.

### D3 — Resumability is derived, and the definition lives in `protocol/`

Two consumers need it (the planner, the stall detector) and neither exists yet, which is exactly when
the mapping gets written twice. Precedent in the repo: `terminal` is a predicate over a state set
rather than a state (architecture.md §3), and `question.blocking_by_design` is derived from `kind` so
the two cannot disagree. Same move: a `RESUMABLE` set plus a small predicate over the kind.

The predicate is **tri-state** — resumable, dead end, or unknown for a null kind. A binary predicate
would have to fold null into one of the two answers, and either choice is a lie a consumer would act
on. Returning `None` matches `question.outcome()`, which already returns `None` for "not decided".

*Alternative considered:* a stored `resumable` boolean. Rejected — two representations of one fact,
and the derived one is cheaper to keep correct.

### D4 — Two nullable reason fields, and the trigger for unifying them

This change makes two fields on one record that are each valid for exactly one `outcome` value. A
third would be a pattern worth collapsing into a single polymorphic `reason` field whose vocabulary
depends on `outcome`.

**Not now, and the reason is legibility.** Two closed sets validate independently and a reader knows
what a value means without consulting `outcome` first; one field with three vocabularies is one field
a reader must decode. **Recorded trigger** (rule of three, from the shelf): if a third outcome
acquires a typed reason — the obvious candidate being *why was nothing ready* — unify all three then,
with the migration paid once.

### D5 — The drift detector imports the executor read-only

`tests/protocol/test_turn.py` already imports `executor.outcome` read-only to assert every executor
failure kind can be recorded. The same test shape applies here: every `RunOutcome` whose narrowing is
`Outcome.BLOCKED` must have a `blocked_kind` to land on. A read-only import from a test is not a
dependency of `protocol/` on `executor/` — the direction that matters is unchanged.

This detector earns its place on evidence: assembling `failure_kind` from the executor's typed
failures alone would have dropped `budget_exhausted`, the starvation case the field existed for. The
union had to be taken deliberately, and nothing but a test remembers that.

### D6 — The second dispatched defect produces no change, and the premise is why

The dispatch states that `cancelled` is absorbing and that this fails the discriminator. **Verified
against the code and the tests: it is not absorbing.** `question.QUESTION` gives `cancelled` exactly
one rule, `awaiting → cancelled`; a `cancelled` arriving at a terminal state fails the read, and
`tests/protocol/test_question_fold.py::test_cancelling_an_answered_question_fails_because_a_canceller_could_have_read_the_log`
asserts the message verbatim. `backlog.ITEM` is the same shape (`any non-terminal → cancelled`). The
only absorbed rules in the repo are `timed_out` from a terminal state and `note`/`noted` from any
state. This is the state the previous change deliberately left it in — ruling 4 of 2026-08-16 kept
`cancelled` excluded — so the premise is a stale reading of a decision already taken, not a defect.

**Two things checked beyond the premise, because rejection at read time sounds worse than it is:**

- *Does a stale-view canceller brick the log?* No. `runtime.turn.append` folds the candidate in a
  temporary file and renames over the log only if the fold accepts it, so an illegal `cancelled` is
  refused at write time and the log is never written. The writer gets the error naming the illegal
  transition at the moment it acts — which is a **louder** preservation of "stale view or real
  disagreement" than absorption, where the record would sit in a file nothing reads.
- *Is the signal actually consumed?* No, and this is the real residual. Nothing anywhere calls
  `question.absorbed()`. The one absorbed case retains its evidence and no reader looks at it, which
  is `build-loop.md`'s third write-back trigger — a mechanism that has never fired. Reported, not
  taken: it is a consumer, and no consumer was dispatched.

## Risks / Trade-offs

- **The field is recordable but not recorded** → the two mapping sites are out of scope, so until a
  follow-up dispatch lands, `blocked_kind` is null on every real row. Mitigated only by saying so:
  same interim as `failure_kind`, which spent one change nullable before the executor filled it.
- **`awaiting` may be the wrong granularity** → it collapses "awaiting a question", "awaiting a
  request" and "awaiting another item", which the item's own block already separates. If a consumer
  turns out to need that split at the record level, the fix is to read the item, not to widen this
  enum. Recorded so the widening is a decision rather than a reflex.
- **A tri-state predicate is easy to misuse** → a consumer writing `if resumable(record)` treats
  unknown as a dead end. The spec requires distinguishing unknown; a test asserts the predicate
  returns `None` rather than a boolean for a null kind, which makes the misuse visible in types.
- **Declaring `needs_approval` unbounded fixes nothing** → true, and deliberate. The alternative is
  building the question-raising path in `runtime/`, which is another worker's file and a larger
  change. An S172 violation that is written down is strictly better than one that is not.

## Migration Plan

None needed, and that is a property worth stating. The field is additive and nullable, `from_dict`
treats a missing key as null, and no existing row changes meaning. Rollback is deleting the field;
records written with it would then fail to read on the unknown key — so rollback is forward-only in
practice, which is the same position every other record field is in ([[D002]]).
