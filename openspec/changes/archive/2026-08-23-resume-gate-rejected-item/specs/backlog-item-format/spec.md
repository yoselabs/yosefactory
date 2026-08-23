## MODIFIED Requirements

### Requirement: `gate_rejected` never resets or reclassifies the item

`gate_rejected` SHALL NOT change the item's state and SHALL NOT be confused with `failed`: it does
not consume the item's attempt budget in the sense `failed`/`poisoned` do, and it is not eligible for
`poisoned` on its own. An item may carry any number of `gate_rejected` records while remaining
`doing`.

**A `doing` item whose most recent event is `gate_rejected` is eligible for the scheduler's fast
path**: it may be acted on again directly, without a `released`/`reclaimed` trip through `ready` and
without a new `claimed` event, for as long as its existing lease has not expired. This is the
transition-level guarantee `turn-cycle`'s "Classification is derived from state, never declared"
reads to admit such an item into `eligible()`.

#### Scenario: Repeated gate rejections do not poison the item

- **WHEN** an item accumulates several `gate_rejected` events across retried attempts
- **THEN** its state remains `doing` throughout
- **AND** no `poisoned` event is triggered by `gate_rejected` events alone

#### Scenario: A gate-rejected item is acted on again without a new claim

- **WHEN** an item is `doing`, its most recent event is `gate_rejected`, and its lease has not
  expired
- **THEN** it may be acted on again without any `released`, `reclaimed`, or `claimed` event
  appearing between the `gate_rejected` record and the next record the new attempt appends
- **AND** the item's `attempt` count — read from its most recent `claimed` event — is unchanged
