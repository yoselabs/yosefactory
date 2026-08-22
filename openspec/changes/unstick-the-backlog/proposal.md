## Why

S1021 (`~/Documents/Knowledge/Projects/160-ai-factory/signals/S1021-*.md`): two predicates decide
whether a turn does anything, and there is a gap between them that swallows the factory.

```
   turn.py:242   eligible()     = state == "ready"
   turn.py:254   should_plan()  = nothing non-terminal exists
   backlog.py:38 TERMINAL       = {done, cancelled, poison, duplicate, abandoned}
```

`failed`, `falsified`, `needs_split`, `blocked`, `snoozed`, `claimed`, `doing` are non-terminal and
non-eligible. One item in any of those states means: nothing is eligible (nothing to act on) *and*
planning is forbidden (something non-terminal exists) — every subsequent turn reports
`nothing-ready`, spends $0, exits 0, and the backlog never grows again. Confirmed against the
current transition table (`backlog.py`): `failed` has an edge only to `poisoned`, `falsified` and
`needs_split` have no outbound edge at all, and `blocked`/`snoozed` have edges (`unblocked`/`woke`)
that nothing in `runtime/turn.py` ever writes except the question-backed half of `unblocked`
(`apply_answers`).

The same freeze without anything failing: `expires_at` is written at `turn.py:606`
(`claimed.expires_at`) and read by nothing — confirmed by `git grep expires_at`, which finds the
declaration, `backlog.lease()`, and the writer, and no consumer. A turn that dies after
`claimed`/`started` (crash, OOM, CI timeout) parks its item in `doing` forever, with the same effect
as an explicit `failed`.

Four of today's seven CI runs died at various points; the only reason nothing is currently stuck is
luck about *where* they died.

## What Changes

- **`should_plan` narrows from "nothing non-terminal exists" to "nothing is `claimed`/`doing`."**
  `failed`, `falsified`, `needs_split`, `blocked`, `snoozed` no longer suppress planning — none of
  them has a bound that resolves on its own today (no sweeper reads `blocked`'s deadline or
  `snoozed`'s `scheduled_for`), so treating them as "in flight" was exactly the freeze S1021 names:
  one stuck item forbidding all future work, forever, for free. A backlog holding only such litter
  is now planned around exactly like an empty backlog already is — bounded by the same
  `LoopBound.max_iterations`/`spend_ceiling_usd` that already bounds planning-turn cost, not by this
  predicate. **BREAKING for `turn-loop/wake-and-bound`'s own documented scenario**: a backlog with
  only a `snoozed` item no longer produces free `nothing-ready` turns forever — it now produces a
  paid planning turn, on the same cost schedule an empty backlog already pays. That scenario is
  corrected, not merely re-worded (see spec delta).
- **`claimed`/`doing` leases become reclaimable.** A new `reclaimed` event (`backlog-item-format`)
  returns an item whose `expires_at` has passed to `ready`. The reclaim sweep runs in the same
  deterministic, agent-free "acquire" step that already runs `apply_answers`, before classification
  — so a reclaimed item is visible to `should_plan`/`eligible` in the same turn that reclaimed it.
- **Exhausted retries are poisoned, not reclaimed forever.** The existing `attempt` counter
  (required on `claimed` since the format was defined) and the existing `retryable` field on
  `failed` (required by the format since it was written; never read anywhere in `src/`) now gate an
  automatic `failed` + `poisoned` pair — for a lease that keeps expiring on the same item past
  `Guardrails.max_attempts`, and for an agent-reported `failed` event that is itself not retryable
  or has used its attempt budget. `poison` is terminal: a poisoned item stops consuming turns and is
  visibly stuck (its own log names why), rather than invisibly stuck to the machine.
- **A second, closely-related bug, found wiring the cap: `attempt` could never exceed 1 in
  production.** `take_turn`'s claim step computed it from `backlog.lease(target)` — but `target` is
  always `ready` at that point (`eligible()`'s own definition), and `lease()` reads `None` for any
  state but `claimed`/`doing`. Every fresh claim therefore always computed `attempt = 1`, regardless
  of how many times the item had been claimed, released, or (now) reclaimed before. `backlog.claims()`
  (new) counts the item's full history instead, so the counter this change gates poisoning on can
  actually accumulate. Without this fix, `max_attempts` would never have been reachable through the
  code path that is supposed to reach it.
- **A commit-scoping bug found while wiring the above, fixed as part of it, not separately.**
  `apply_answers`' return value (`moved: list[str]`, the ids of items it unblocked) has been
  discarded since it was written — those items' `unblocked` lines are appended to disk but never
  named in the turn's `commit()` pathspec, so they sit uncommitted in the tree until something else
  incidentally sweeps them up, and — under `Places.local`, where `places.queue == places.workspace`
  — read as the *agent's* dirty tree by `_finish`'s own `tree_is_dirty` check. The reclaim sweep this
  change adds writes to the same class of file for the same reason, so it would inherit the
  identical defect if wired the same way `apply_answers` was. Both are fixed together: every sweep
  step now returns the paths it touched, and every path this turn's `_finish` commits includes them
  (`design.md` covers the sequencing).
- **A freeze becomes loud.** `runtime/loop.py::main()` (interactive and `scheduled_main`, the
  entrypoint `ops/launchd/dev.yosefactory.loop.plist.template` already names) checks
  `run-guardrails/stall-detection`'s own verdict after `run_loop` returns and exits with the verdict's
  own non-zero code (`STALLED` → 1, `STARVED` → 2) rather than always returning 0. `stall.py` itself
  is unchanged — it already computes the right verdict and exits correctly when invoked directly;
  nothing in this repository's own process ever consulted it. This is deliberately *not* a new CI
  workflow or a new scheduler wrapper — `loop.py`'s own docstring already draws that boundary
  ("a `.github/workflows/*.yml` that has never fired is exactly what S195 found nine of already"),
  and building the cron itself is out of scope here. Wiring the exit code of an entrypoint this repo
  already ships (and a plist template already names) is the smallest change that makes a freeze
  visible to whatever *does* invoke that entrypoint, today or later.

## What does NOT change

- **No sweeper for `blocked`'s deadline or `snoozed`'s `scheduled_for`.** `eligible()`'s own
  docstring already says "there is no sweeper" for waking a snoozed item; building one is a real,
  separate feature (reading a question's `deadline` cross-file, firing `on_timeout` policy,
  wiring `woke`) and is not required to stop the freeze — narrowing `should_plan` already stops it
  for these two states, at the cost of allowing paid re-planning around them (bounded by existing
  loop bounds, argued above). `tensions.md`/`backlog.md` gets a line naming this as the next thing
  to build if re-planning around blocked/snoozed items is ever measured as costly slop rather than
  a bounded, occasional cost.
- **No cross-machine compare-and-swap push.** `take_turn(cross_machine=True, cas_push=False)` is
  already refused today; this change does not touch that gate. Reclaiming a lease is safe by
  construction against a still-alive "dead" turn in the one topology this repository actually runs
  (`cross_machine=False`, `single_flight`-protected, one queue clone per turn) — see `design.md` for
  what happens to a still-alive turn's own write when a reclaim has already landed.

## Impact

- Affected specs: `backlog-item-format` (new `reclaimed` event, `poisoned`'s attempt-cap trigger
  wired), `turn-cycle` (should_plan narrowed; reclaim sweep runs before classification),
  `turn-loop/wake-and-bound` (the now-inaccurate "snoozed backlog costs nothing" scenario
  corrected), `run-guardrails/stall-detection` (the CLI entrypoint now surfaces the verdict).
- Affected code: `src/yosefactory/protocol/backlog.py`, `src/yosefactory/runtime/turn.py`,
  `src/yosefactory/runtime/config.py` (`Guardrails.max_attempts`), `src/yosefactory/runtime/loop.py`.
- New ADR: `decisions/0012-lease-reclaim-and-should-plan-narrowed-to-in-flight.md`.
