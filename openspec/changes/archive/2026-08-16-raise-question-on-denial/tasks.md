# Tasks

- [x] 1. Confirm no production writer of `asked`/item-`blocked` exists for this path — re-checked
      against disk after `write-the-reason-fields` and the trailer change both landed; `blocked()`
      (`runtime/turn.py:466-478`) still only calls `_finish`, unchanged
- [x] 2. Add `question_deadline_hours` to `Guardrails.DEFAULTS`, required int with a default (not
      `_OPTIONAL` like `cost_ceiling_usd` — a question's `deadline` has no "send nothing" state),
      documented as a guess like its four siblings
- [x] 3. In `_dispose`'s `blocked()` path, for `kind is BlockedKind.NEEDS_APPROVAL` only: write the
      `asked` question, append the item's `blocked` event, then call `_finish` with the question
      file added to `paths` — `_finish`'s existing `commit(..., run_id=run_id)` call picks it up and
      threads the platform trailer through automatically; no new commit call site
- [x] 4. Cover: a `NEEDS_APPROVAL` result leaves the item `blocked` (not `doing`), with a question
      file whose `qid` matches the item's `awaiting.ref`, and the commit that lands it carries the
      `Yosefactory-Run` trailer like every other platform commit
- [x] 5. Cover: `apply_answers` unblocks the item once that question is answered, returning it to
      `doing` (`return_to`), with no change to `apply_answers` itself
- [x] 6. Cover: `REFUSED` is unaffected — no question, no `blocked` item event, ledger row only
- [x] 7. Record Loop 2's disposition (deferred, not built) where the sweeper's future owner will
      find it — this exploration.md, cross-referenced from wherever the sweeper work is tracked
- [x] 8. Closing report: no test in this repo drives `take_turn` against a real executor — every
      one calls `claude.run()` in isolation (YF-6's finding). This change adds a wiring receipt
      (item ends `blocked`, question file exists, `awaiting.ref` matches) and no live receipt (a
      real denial producing a real question row on disk). Say so plainly; a green `make check`
      here does not mean more than that.

## Open loop, no owner

**A planning-turn denial (no claimed item) writes no question and falls through to the ledger-only
ending.** The handling is correct given what exists — there is no item to suspend a question
against — but the result is an open loop under S172, not a closed edge case:

```
   denial during an item turn    → question raised → Denis sees it → loop closes
   denial during a planning turn → ledger row only → nobody is asked → nothing is waiting
                                  → the approval is needed and unrequested, forever
```

This is smaller than the defect this change fixes — no item is stranded, because no item exists —
but it is the same shape one level up: `refused` reaching a ledger-only ending is correct *by
design* (nothing arriving changes a refusal); a planning `needs_approval` reaching the same ending
is unhandled *by omission*, the same distinction that motivated this whole change.

**Not fixed here, and not a small patch.** A question raised during planning has no item to hang
off, no obvious `return_to`, and no obvious resumption target — that is a real design question
(what does it suspend, what resumes it) and belongs to its own dispatch, not appended to this one.
Recorded here so it is not lost, and cross-referenced from wherever planning-turn design is tracked
next.
