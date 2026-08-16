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

## Also covered, beyond the original list

- A planning-turn denial (no claimed item) writes no question and falls through to the ledger-only
  ending, matching `refused`'s behaviour — there is nothing to suspend a question against.
