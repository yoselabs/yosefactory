## REMOVED Requirements

- ### Requirement: The loop is bounded, and the bound is mandatory

  This requirement bundled two invariants: `max_iterations` is mandatory (kept, see ADDED below
  under a new name), and an optional cumulative `spend_ceiling_usd` with a derived per-turn ceiling
  (deleted, not modified — K D034: the design it reached for, a cross-run cumulative spend view, is
  explicitly unwanted, and the check itself never fired in production; see design.md). Removed as a
  whole block per Article XIV, rather than MODIFIED down to a smaller scenario set, so archive does
  not have to be trusted to drop the deleted scenarios silently.

  **Correction, added after archiving:** the bullet form above (`- **name** — text`) does not match
  `openspec`'s REMOVED-name parser, which requires either a bare `### Requirement:` header or a
  bullet of the literal form `- ### Requirement: <name>` (`core/parsers/requirement-blocks.js`,
  `parseRemovedNames`). The first archive run parsed zero REMOVED names, so the stale old block
  survived in `openspec/specs/turn-loop/wake-and-bound/spec.md` unremoved (`+1 added, -0 removed`)
  until caught by the mandated post-archive diff check (Article XIV) and fixed by hand, same commit.
  This file is corrected to the parseable form for the historical record; the fix that actually
  matters landed directly in `openspec/specs/`.

## ADDED Requirements

### Requirement: The loop is bounded by iteration count

`LoopBound.max_iterations` SHALL be a required positive integer with no default; a `LoopBound`
constructed with a non-positive or missing `max_iterations` SHALL be refused before the loop runs.
`run_loop` SHALL stop the first time the number of turns run reaches `max_iterations`.

**Reason, carried with the rule:** a self-chaining loop is the first mechanism in this program
capable of spending money with nobody between iterations. A bound with an infinite mode defeats the
property the bound exists for. `max_iterations` is unchanged by K D034 (ADR-0003 is not disturbed);
what D034 removes is the cumulative `spend_ceiling_usd` half of the requirement this one replaces —
the only enforcement point for spend that remains is the per-turn `Guardrails.cost_ceiling_usd`
(`claude-executor/cost-ceiling`), untouched by this change.

#### Scenario: An unbounded `LoopBound` is refused
- **WHEN** `LoopBound` is constructed with `max_iterations=0`, a negative value, or omitted
- **THEN** construction raises before any turn runs

#### Scenario: The loop stops exactly at `max_iterations`
- **WHEN** `max_iterations` turns have completed
- **THEN** the loop returns with `StopReason.MAX_ITERATIONS` and no further turn runs
