## Why

[[D032]] (`~/Documents/Knowledge/Projects/160-ai-factory/decisions/D032-an-event-payload-is-a-validated-structure-not-a-bare-dict.md`):
an event payload SHALL be a validated structure, not a bare dict, following [[S246]] — a latent
`AttributeError` in `backlog.context()`, found by an unsanctioned agent, in code written, reviewed
and live-verified the day before. `Rule.required`/`Rule.patterns` (`protocol/eventlog.py`) already
declare which paths must be *present*; nothing declares their *type*, so `required=(("resolution",),)`
is satisfied equally by the string `"timeout"` and by a mapping — exactly the gap `context()` fell
into. Neither `ty`, `ruff`, nor 400+ passing tests saw it, because the only place the shape is
stated is prose in `openspec/specs/backlog-item-format/spec.md`, which does not fail a build.

## What Changes

- **Part 1 — the defect.** `backlog.context()`'s `unblocked` branch guards `resolution` with
  `isinstance(resolution, Mapping)` before calling `.get("answer")`, so the literal string
  `"timeout"` (the deadline-sweep resolution the spec already requires) folds to no answer instead
  of crashing. Taken as one hunk from `sweep-blocked-and-snoozed-deadlines` commit `2262f7e`
  ([[S246]]) — nothing else from that branch.
- **Part 2 — the mechanism.** `eventlog.Rule` grows a `types` field: `Mapping[Path_, type | tuple[type, ...]]`,
  checked in `_check_payload` exactly where `required` and `patterns` already are — same function,
  same loop shape, one more declared property of the same paths. No second schema. Types declared
  for the three events `context()` actually reads: `gate_rejected.report`/`.attempt`,
  `failed.reason`/`.attempt`/`.retryable`, and `unblocked.resolution` (the type `(str, Mapping)`,
  since the spec legitimately allows both — the deadline-timeout string and the
  answer-carrying dict). This runs inside `_fold`, on every record read from disk, so a
  hand-seeded or historical event with the wrong shape fails the read exactly like an unknown event
  or a missing required field does today — not only events a current writer could produce.
- **Spec delta.** `backlog-item-format/spec.md`'s vocabulary table and its `unblocked` scenario
  already describe both `resolution` shapes in prose (`carry-inherited-context-into-the-turn`'s
  MODIFIED block). This change adds one scenario: a payload whose declared field has the wrong
  type fails the read, naming the field, the value, and the expected type(s) — same posture as the
  existing "malformed on_timeout" scenario, extended from pattern-mismatch to type-mismatch.

## What does NOT change

- **No pydantic, no per-event model classes.** D032 leaves the mechanism open; this change takes
  the smallest of the three candidates it lists (extend `Rule`) because it is the only one that
  does not add a second declaration alongside `Rule.required`/`.patterns` — see `design.md`.
- **`scheduled_for()`, `sweep_deadlines()`, `runtime/turn.py` from the unsanctioned branch.** Out of
  scope, unreviewed, not taken.
- **Every other event's payload.** `created`, `claimed`, `blocked`, `done`, etc. carry no type
  declarations here. `design.md` states the boundary and what remains open.
- **Nested/sub-key validation of `resolution`'s dict branch** (`qid`, `by`, `answer` individually
  typed). Out of scope — the defect this change closes is a top-level shape mismatch, not a
  sub-field one.

## Impact

- `src/yosefactory/protocol/eventlog.py` — `Rule`, `_check_payload`.
- `src/yosefactory/protocol/backlog.py` — `context()`'s `unblocked` branch; `ITEM.rules` for
  `gate_rejected`, `failed`, `unblocked`.
- `openspec/specs/backlog-item-format/spec.md` — one new scenario, via this change's delta.
- `tests/protocol/test_backlog_fold.py`, `tests/protocol/test_eventlog*.py` (new or existing).
