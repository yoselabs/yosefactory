## Why

S236 (`~/Documents/Knowledge/Projects/160-ai-factory/signals/S236-*.md`), measured against a real
executor run: `gate_rejected` is `doing -> doing` (ADR-0015) and does not touch the lease. The item
stays claimed by the owner that just failed, so `eligible()` (`state == "ready"` only) will not admit
it again until `expires_at` passes. In the measured run — a live `.dev-workspace` loop, well inside
its 45-minute default lease — the next three loop iterations found nothing eligible and the run
stalled with iterations left unspent.

`eligible()`'s own spec (`backlog-item-format`, "`gate_rejected` never resets or reclassifies the
item") already says an item may carry any number of `gate_rejected` records while remaining `doing`,
and ADR-0015 chose `doing -> doing` specifically so a rejection stays retryable **within the same
attempt** rather than burning `attempt`'s budget. Nothing today acts on that intent: the only route
back to `ready` is `reclaim_expired`, which fires on lease expiry and — via the ordinary `claimed`
flow — increments `attempt` on the very next claim. So a rejection that happens to be caught before
`expires_at` currently has no path back to work at all; one that survives to `expires_at` gets
retried, but only by spending an attempt it was never supposed to cost.

**What this does not fix, stated up front because the dispatch's framing needs correcting.**
`Guardrails.wall_clock_seconds` defaults to 45 minutes and is capped at six hours
(`runtime/config.py`); a nightly cron wakes roughly once per 24 hours. Since the lease is always
long-expired by the next scheduled wake, `reclaim_expired` already reclaims and retries a
gate-rejected item on that wake today, attempt bump and all — the "days before an item poisons"
outcome the dispatch describes is not caused by this defect and is not changed by fixing it; it is
the cron's own cadence times `max_attempts`, and it was already true before this change. What this
change fixes is the same-lease-window case S236 actually measured: a wake that arrives *before* the
lease expires (a live loop with more than one iteration, a cron interval shorter than the lease, or
a future change to either) finding nothing eligible when a free, same-attempt retry was available.

## What Changes

- **`eligible()` admits a second case: `doing` whose most recent event is `gate_rejected`.** Such an
  item is picked exactly like a `ready` one, without a new `claimed`/`started` pair — `attempt` and
  `owner` are read from the lease already on record, unchanged. No new event, no state transition,
  no protocol change: `gate_rejected` already declared `doing -> doing`
  (`decisions/0015-gate-rejection-is-a-new-event-answer-text-is-copied-not-referenced.md`); this
  makes the scheduler act on what the state machine already permits.
- **`reclaim_expired` is untouched.** It still reclaims (or poisons, past `max_attempts`) any
  `claimed`/`doing` item — including a gate-rejected one — once its lease genuinely expires. This is
  the only mechanism that bounds an item that can never satisfy its gate; the new fast path only
  ever fires *before* that point, so it cannot make the bound worse. See `design.md` for the exact
  wall-clock arithmetic, unchanged by this proposal.

## What does NOT change

- **`max_attempts`'s meaning.** A resumed-after-rejection turn never appends a new `claimed`, so it
  never increments `attempt`. The counter still means exactly what unstick-the-backlog defined it to
  mean: how many times the item has been claimed from `ready`.
- **`reclaim_expired`'s own logic.** Not touched; still the sole path back to `ready`, still the sole
  path to `poison` for an item that keeps failing. This proposal adds a path that runs *before*
  reclaim would fire, not a replacement for it.
- **No owner-identity check.** The fast path resumes whichever item `eligible()` admits, using the
  current turn's `owner` for any new events it appends, regardless of which owner the existing lease
  names. This repository has exactly one operator identity (D005); a real multi-owner collision is
  out of scope and would need its own design.

## Impact

- Affected specs: `turn-cycle` (`eligible()`'s admitted states), `backlog-item-format` (a scenario
  naming the fast path explicitly; no vocabulary or transition-table change).
- Affected code: `src/yosefactory/runtime/turn.py` (`eligible()`, the claim/resume branch in
  `take_turn`).
