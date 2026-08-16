## Why

`question-frame` shipped with seven kinds; M600's closed set has eight. The missing one is
`skip-the-skill` — from S090, the offer to skip a skill when frustration is detected. A closed set
that is missing a member is not a closed set, and the gap would surface as an invalid record the
first time the system emits one.

Promotion: **M600** (the typed question's vocabulary), with **S090** (the demand it came from) and
**S062** (why kind routes rather than gates).

## What Changes

- `skip-the-skill` is added to the closed set of question kinds, bringing it to eight.
- The spec records what makes this kind unlike the other seven: it is **emitted by the system**
  rather than requested by a stage. S062's constraint — kind routes, never gates, and no stage
  pre-declares its kinds — is what makes that harmless rather than a special case needing its own
  machinery.
- `skip-the-skill` is blocking-by-failure, like every kind except `elicitation`.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `question-frame`: the closed set of kinds gains `skip-the-skill`, and the requirement states
  that a kind may be system-emitted.

## Non-goals

Two changes were considered together with this one and are **deliberately deferred**, so whoever
picks them up inherits the reasoning instead of rediscovering it:

- **The absorb rule for a late `timed_out`** — a sweeper's timeout losing a race with an answer
  should be absorbed as a declared no-op rather than failing the read. It is **blocked on a fold
  change**: `_check_from` in `protocol/eventlog.py` rejects every event from a terminal state
  unless `from_states` is exactly `ANY`, and one event name gets exactly one rule, so `timed_out`
  cannot be both `awaiting → timed_out` and `terminal → no-op`. The agreed fix is multiple rules
  per event, first matching `from_states` winning. Until that lands, a late `timed_out` fails the
  read loudly — rare, visible, and repairable by hand.
- **Removing `deadline` / `on_timeout` from the item's `awaiting` block** — the question owns them
  and the item should carry only the correlation id and `return_to`. That is a change against
  `backlog-item-format`, not this capability.

Also out of scope: any change to how kinds are validated, routed, or prioritised. Only the set
grows.

## Impact

- `openspec/specs/question-frame/spec.md` — one requirement modified.
- `questions/README.md` — the kinds table gains a row.
- No fixtures change: `skip-the-skill` needs no new record shape, and inventing an example of the
  system offering to skip a skill would be fiction ahead of the first real one.
