# ADR-0012 — `should_plan` narrows to `claimed`/`doing`; leases reclaim and poison rather than freeze

**Status:** Accepted
**Date:** 2026-08-22
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** Re-planning around a stuck-but-not-empty backlog (`failed`/`blocked`/`snoozed`
items with nothing ready) is measured, over a real run of nights, to cost materially more than
planning around an empty backlog already does — e.g. the planner reliably re-proposes work that
collides with what is already stuck, rather than treating it as inert. At that point build the
deadline/`scheduled_for` sweeper `eligible()`'s own docstring already names as missing ("there is no
sweeper"), and re-tighten `should_plan` to respect a `blocked`/`snoozed` item's own bound for as
long as that bound holds. Also revisit if `take_turn(cross_machine=True, cas_push=True)` is ever
actually built — reclaim's safety argument here is scoped to the currently-supported
`cross_machine=False`, single-clone-per-turn topology; a real CAS push changes what "reclaim" needs
to guarantee.

## Context

S1021 (`~/Documents/Knowledge/Projects/160-ai-factory/signals/S1021-*.md`): `eligible()` (state ==
`ready`) and `should_plan()` (nothing non-terminal exists) leave a gap that swallows the factory —
one item in `failed`, `falsified`, `needs_split`, `blocked`, `snoozed`, `claimed`, or `doing` makes
nothing eligible *and* forbids planning, forever, for $0, silently. The same freeze is reachable with
no agent failing anything: `claimed.expires_at` is written and read by nothing, so a turn that dies
after claiming an item parks it in `doing` permanently. Both have already happened in ordinary CI
operation (four of seven runs on the day this was found died at various points).

## Decision

1. **`should_plan` narrows to "any item is `claimed`/`doing`."** Considered and rejected: leaving it
   as "any non-terminal" (that is S1021 itself); narrowing it to "any item with a live, unexpired
   bound" (`blocked`'s deadline, `snoozed`'s `scheduled_for`) — closer to the original design intent,
   but rejected for this change because nothing today fires those bounds (no sweeper reads a
   deadline or a `scheduled_for` to unblock/wake anything), so the predicate would still freeze on
   those two states. `claimed`/`doing` is the smallest predicate that stops the freeze for all seven
   states S1021 names and still means something, because the reclaim sweep below guarantees a
   `claimed`/`doing` item cannot camp past its own lease.
2. **Leases become reclaimable, and reclaiming is capped by the `attempt` counter.** A new
   `reclaimed` event (`claimed`/`doing` → `ready`) fires in the same deterministic, agent-free sweep
   step that already runs `apply_answers`, before classification. Once an item's most recent
   `attempt` (required on `claimed` since the format was defined, previously read by nothing — and,
   per item 5 below, previously incapable of exceeding 1) reaches `Guardrails.max_attempts`, the
   sweep appends `failed` (`retryable: false`) then `poisoned` instead
   of `reclaimed` — a crash-looping item stops consuming turns and becomes terminal, visibly, rather
   than either freezing the factory or retrying forever.
3. **`failed.retryable` is read for the first time.** Required by the format since it was defined,
   read by no code in `src/` until now. A `failed` event carrying `retryable: false` poisons the item
   immediately, regardless of attempt count — the agent's own judgment that retrying is pointless is
   trusted once, rather than re-litigated `max_attempts` times.
4. **The paid-planning tradeoff is accepted, not hidden.** Once `failed`/`falsified`/`needs_split`/
   `blocked`/`snoozed` stop suppressing planning, a backlog holding only such items looks like an
   empty backlog to `should_plan` and triggers a paid planning turn instead of a free `nothing-ready`
   one. This is not a new unbounded cost: an empty backlog already triggers planning on every wake,
   bounded by `LoopBound.max_iterations` and (unattended) `spend_ceiling_usd`. A stuck-but-not-empty
   backlog now costs exactly what an empty one already costs, no more — see `design.md` (this
   change's `openspec/changes/unstick-the-backlog/design.md`) for the full argument.
5. **A second bug, found wiring the cap: `attempt` could never exceed 1 in production.**
   `take_turn`'s claim step computed the next `attempt` from `backlog.lease(target)`, but `target` is
   always `ready` when claimed (`eligible()`'s own definition), and `lease()` reads `None` for any
   state other than `claimed`/`doing` — so every claim, forever, computed `attempt = 1`, regardless
   of history. `backlog.claims()` (new) counts every `claimed` event the item's full log carries
   instead, surviving the reset `released`/`reclaimed` both perform. Without this fix, the
   exhaustion cap this change adds would gate on a number that could never move.
6. **A commit-scoping bug, found wiring the reclaim sweep, is fixed in the same change.**
   `apply_answers`'s return value (the item ids it moved) has been discarded since it was written —
   those items' new lines were appended to disk but never named in the turn's `commit()` pathspec,
   so they sat uncommitted, and under `Places.local` (queue == workspace) misread as the agent's own
   dirty tree. The reclaim sweep would have inherited the identical defect sitting in the same
   position; both are fixed together by threading every sweep step's touched paths into the commit.
7. **Cross-machine correctness is named, not built.** A reclaimed lease's original turn, if not
   actually dead, still appends its own event safely to its own local clone (D002 holds structurally
   — `append()` only ever adds lines) but its eventual `push_repo` is rejected as non-fast-forward
   once the reclaim has landed first; today that only raises a `RuntimeWarning`
   (`PublicationFailed`), so the result is a lost turn (wasted work), not corrupted item state. Fixing
   this needs the compare-and-swap push `take_turn`'s own `cross_machine`/`cas_push` parameters
   already name and refuse — out of scope for un-sticking the backlog, and already gated off by an
   existing `TurnError` for the one topology (two live machines) where it would matter.
8. **The freeze becomes loud via an exit code, not a new workflow.** `runtime/loop.py::main()`
   (interactive) and `scheduled_main()` (the entrypoint `ops/launchd/dev.yosefactory.loop.plist.template`
   already names) check the stall verdict after `run_loop` returns and exit with its own non-zero
   code. `stall.py` itself is unchanged — it was already correct and already invocable; nothing in
   this repository's own process ever called it. Building a CI workflow to invoke it is explicitly
   left undone, matching `loop.py`'s own stated position that an unfired `.github/workflows/*.yml` is
   exactly what S195 already catalogued nine of.

## Consequences

- A stuck item (of any of the seven kinds S1021 names) no longer forbids all future planning.
- A crash-looping claim stops after `max_attempts` reclaims, poisoned and visible in its own log,
  rather than retried forever or frozen forever.
- Planning cost on a stuck-but-not-empty backlog rises to match an empty backlog's existing cost —
  a real, named, bounded tradeoff, not a silent one.
- `blocked`/`snoozed` items with no answer/wake mechanism remain individually stuck — this decision
  does not resolve them, it stops them from freezing everything else. Building the deadline/wake
  sweeper remains open work, named in the revisit trigger above.
- The queue-repo commit produced by `apply_answers` (pre-existing) and by the new reclaim sweep is
  now always complete — no more silently-uncommitted sweep writes.
- A stall is visible in the exit code of an entrypoint this repository already ships, without new
  scheduling infrastructure.
