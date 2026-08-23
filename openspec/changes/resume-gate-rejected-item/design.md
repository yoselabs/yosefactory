## The tension, and how it resolves

ADR-0015 chose `gate_rejected: doing -> doing` so a rejection "must remain retryable within the same
attempt." Two ways to make a `doing` item reachable again were on the table:

1. **Release the lease and let the item flow back through `ready`.** Whatever writes the release —
   shortening `expires_at` on `gate_rejected`, or a bespoke early-reclaim — the only route from
   `ready` back to `claimed` is the existing `take_turn` claim step, which always computes
   `attempt = backlog.claims(target) + 1`. Any such design increments `attempt` on the very retry
   ADR-0015 said must not cost one. **Rejected**: it undoes the ADR by construction, not by an
   oversight fixable later.
2. **Recognize the item as directly resumable from `doing`, never touching `ready`.** `eligible()`
   admits `doing` whose last event is `gate_rejected`; `take_turn` skips the claim step entirely for
   such a target and re-enters the executor with the lease's existing `attempt`/`owner`. **Chosen.**

(2) is not a new mechanism bolted on — it is `eligible()` catching up to what `backlog.ITEM`'s own
rule table and `backlog-item-format`'s spec already say: `gate_rejected` changes nothing about the
item's state, and the item "may carry any number of `gate_rejected` records while remaining `doing`."
Nothing enforced that today; `eligible()` simply never looked.

## Why this does not need a new poison trigger

The obvious worry: if resuming a rejected item never increments `attempt`, and `eligible()` will
keep offering it back to the executor, what stops an item whose gate can never pass from retrying
forever?

`backlog-item-format`'s own spec already answers this, in the requirement this change does not
touch: *"no `poisoned` event is triggered by `gate_rejected` events alone."* Poisoning is `failed`'s
job, gated on `attempt`; `attempt` only moves through an actual `claimed` event, and the only path to
a fresh `claimed` is `reclaim_expired`, unmoved by this change. So the backstop is exactly the
mechanism unstick-the-backlog already built: **the fast path this change adds only operates before
the lease expires.** The moment it does not — a genuinely stuck executor, a wake that never comes,
whatever — `reclaim_expired` takes over on the very next turn exactly as it does today, reclaiming
under the cap and poisoning past it. This change adds a path that runs earlier; it does not remove
the one that already bounds the item.

## What the bound actually is, and the number the dispatch got wrong

Walked against the real defaults (`runtime/config.py`): `wall_clock_seconds` default 45 minutes,
hard ceiling six hours; `max_attempts` default 3; a nightly cron wakes roughly once per 24 hours.

```
  day 0   claim (attempt 1) -> gate_rejected -> doing, attempt 1
  day 1   lease long expired -> reclaim_expired: attempt(1) < 3 -> reclaimed -> claim (attempt 2)
          -> gate_rejected -> doing, attempt 2
  day 2   lease expired -> reclaim_expired: attempt(2) < 3 -> reclaimed -> claim (attempt 3)
          -> gate_rejected -> doing, attempt 3
  day 3   lease expired -> reclaim_expired: attempt(3) >= 3 -> failed + poisoned, no reclaim
```

**Four wakes, roughly 72-96 wall-clock hours on a nightly cron, to poison an item that can never
satisfy its gate** — with default `max_attempts=3`. This is *unchanged* by this proposal: at a
24-hour cron cadence, the 45-minute-to-6-hour lease is always expired by the next wake regardless of
whether the fast path exists, so `reclaim_expired` was already doing this, attempt bump and all,
before this change.

The dispatch's framing — "a gate rejection costs roughly 24 hours per attempt, and `max_attempts`
turns that into days" — states the correct number (days) for the wrong reason. It is not caused by
the lease-release defect and this change does not reduce it; the cron's own once-a-day cadence is
the floor no fix here can move. What the defect actually costs, and what this change actually buys
back, is wall-clock *inside* a single lease window: a live loop (`runtime/loop.py`, `max_iterations`
> 1) or any deployment whose wake interval is shorter than `wall_clock_seconds` — which is exactly
the shape of the run S236 measured, and the shape a future change to either knob could produce again.

## Why no owner check on the resume path

`take_turn`'s `owner` parameter is a constant configuration value in every deployment this repository
has (`--owner` defaults to the literal `"loop"` in `runtime/loop.py`'s CLI) — D005 scopes this
platform to one operator, so there is exactly one identity acting through it, not a pool of workers
contending for the same lease. The resume path therefore does not compare the current turn's `owner`
against the lease's recorded `owner` before acting; it uses the current turn's `owner` for whatever
new events it appends, same as the fresh-claim path already does. A real multi-owner deployment
would need to decide what a mismatch means (refuse? reclaim first? escalate?) and is out of scope —
named here so it is not silently assumed away.
