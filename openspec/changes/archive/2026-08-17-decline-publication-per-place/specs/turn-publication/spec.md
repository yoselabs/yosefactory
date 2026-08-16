## ADDED Requirements

### Requirement: Publication may be declined per place, and declined is not skipped

`Places` SHALL carry, independently for `workspace` and for `queue`, whether that place may be
published by this turn. When a place is not publishable, `publish` SHALL NOT invoke a push for it,
and SHALL report the place's status as `declined`.

`skipped` SHALL be reported only for a place that was publishable but had no `origin` remote
configured. `declined` SHALL be reported only for a place the caller marked not publishable.
Neither status SHALL be produced by the other's cause, and a place that is both not publishable and
has no `origin` configured SHALL still report `declined` — the caller's instruction is checked first
and unconditionally, so `push_repo` is never invoked for a declined place and its own remote state is
never consulted.

Absent an explicit choice, both places SHALL be publishable — this requirement changes whether
publication can be declined, not whether it happens by default ([[D022]] grants push; declining is an
opt-out a caller states, not a new default).

#### Scenario: A declined place is not pushed

- **WHEN** a turn advances and `workspace` is marked not publishable
- **THEN** no push is attempted against the workspace
- **AND** its publication result reports `declined`

#### Scenario: Declined and skipped are never conflated

- **WHEN** a place is marked not publishable and also has a real, reachable `origin` configured
- **THEN** its publication result reports `declined`, never `skipped` or `pushed`

#### Scenario: An unstated choice publishes, exactly as before this requirement existed

- **WHEN** a turn's `Places` supplies no opinion on either place's publishability
- **THEN** both places publish exactly as `turn-publication`'s other requirements already specify
