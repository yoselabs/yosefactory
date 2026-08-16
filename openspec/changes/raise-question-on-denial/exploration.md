# Exploration — two loops dispatched together, one live victim

Dispatched as one task: `needs_approval` is a dead end by omission (D021 §…, S172), and
`question.absorbed()` has a mechanism and no consumer. Both are read against the tree as it stands
today (`runtime/turn.py` is mid-edit under `write-the-reason-fields`, uncommitted, read as-is).

## Loop 1 — a denial writes no question

`src/yosefactory/runtime/turn.py:429-452`, the `blocked()` closure inside `_dispose`:

```
NEEDS_APPROVAL ──▶ blocked(detail, kind) ──▶ _finish(outcome=BLOCKED, blocked_kind=NEEDS_APPROVAL)
```

`_finish` writes exactly one thing: the turn's own ledger row (`TurnRecord`, `ledger/runs/`). It
never touches `backlog/items/<id>.jsonl`. So the sequence a denial actually produces is:

1. item enters `doing` (via `claimed` → `started`, committed before the agent ran)
2. agent asks for a tool, is denied, run ends
3. turn ledger gets a row: `outcome=blocked, blocked_kind=needs_approval`
4. **the item itself never gets a `blocked` event.** It is still `doing`.

`eligible()` (`turn.py:164`) admits only `state == "ready"`. `doing` is not `ready`, so no later turn
ever picks this item up again — not even after its lease (`expires_at`, written at `claimed`) has
passed, because nothing reads `expires_at` to reclaim a stale claim. The item is not merely
unresumable; it is **invisible** to every later turn. `bd`-style `ready`/`blocked` listings would
both miss it — it is neither.

This is the concrete shape of the director's framing: a permission denial writes no question, so it
acquires no `deadline`/`on_timeout`/`return_to`, and nothing sweeps it — because nothing was ever
asked in the first place, not because the sweep is missing.

Confirmed against `backlog.py`'s own `blocked` rule: it requires `awaiting.{kind,ref,who,since,
return_to,nudge_at}` — the item-side half already exists and is unused for this path. `question.py`'s
`asked` rule requires `{item,kind,to,text,answer_type,return_to,deadline,on_timeout}` — same story.
Nothing in this repository has ever called `question.py`'s writer path (grepped; zero non-test,
non-declaration hits on `"asked"` as a written event).

**Builds on `write-the-reason-fields` (in flight, uncommitted):** that change is what makes
`blocked_kind` reach the turn record at all. Before it, `_TO_PROTOCOL`/`protocol_outcome` had no
production caller and every non-success run recorded `failed`. After it lands, the *ledger* correctly
types the wait — but the fix below is still needed regardless of that change's fate, because typing
the wait in the ledger and giving the item something to wait *on* are different gaps. This proposal
does not depend on that change landing first; it depends only on `blocked_kind` existing as a value,
which is already true in the pre-image (`executor/outcome.py`'s `_TO_BLOCKED_KIND`).

## Loop 2 — `absorbed()` has no consumer, and also no producer

`question.absorbed()` (`src/yosefactory/protocol/question.py:121`) is exercised by exactly one test
(`tests/protocol/test_question_fold.py::test_a_sweeper_that_lost_the_race_is_absorbed_and_kept`) and
zero production code. That much matches the dispatch.

Looking for who *should* read it surfaced a fact one level under the question asked: **there is no
sweeper.** `turn.py:165`'s own docstring says it plainly — "Waking a snoozed item is a sweeper's job
and there is no sweeper" — and a repo-wide grep for `timed_out` finds the word only in the
declaration, its docstring, and the one test that constructs the record by hand. Nothing in `src/`
ever appends `timed_out`.

That means `absorbed()`'s precondition — a sweeper racing a human answer — cannot occur in this
codebase today. Not "occurs but nobody reads it": **cannot occur at all.** The mechanism is not an
unwired consumer problem; it is downstream of a producer that does not exist yet.

Building a reader now would be building against a fixture, not a subject — the exact shape of S194
run in reverse: a consumer whose tests pass forever because nothing has ever fed it a real row is as
blind as a field nobody writes. Given the choice the dispatch offered — a reader, a detector, or the
conclusion that absorption should not retain what nobody looks at — none of the three is answerable
yet. Recommendation below.

## One change or two

Argued rather than assumed, per the dispatch:

**One applicable change, one documented deferral — not two applicable changes, and not one merged
change.**

- They share a subject (a loop that cannot close because the thing that would close it was never
  written) but sit on opposite sides of a producer that doesn't exist. Loop 1 is upstream of the
  sweeper — items get stranded whether or not a sweeper ever ships. Loop 2 is downstream of it —
  its whole premise is a sweeper racing an answer.
- Loop 1 has a live victim now: every `NEEDS_APPROVAL` run today strands its item silently. Loop 2
  has no victim to point at: `absorbed()` has never fired outside a test.
- Merging them into one proposal would make the deferred half look like scope creep on the live half,
  and splitting the deferred half into its own applicable change would mean writing a consumer with
  no real input to verify it against — a second S194 risk, not a fix for the first.

So: this change proposes only Loop 1. Loop 2's disposition is recorded here as a finding, not a
spec change:

**Recommendation for Loop 2: defer.** Do not build a reader, detector, or removal now. The right
trigger is "a sweeper exists" — at that point `absorbed()` has a real producer for the first time,
and the honest question (reader vs. detector vs. drop-the-retention) becomes answerable against real
races instead of a hand-built fixture. Whoever builds the sweeper (`runtime/` + stall-detector
territory — YF-3's remit per this dispatch) inherits the question; this exploration is the pointer.
Absorption itself is not touched — it is cheap, already tested, and correct by construction from the
fold's own rule-ordering (`eventlog.py`'s first-rule-wins). Nothing here proposes removing it.
