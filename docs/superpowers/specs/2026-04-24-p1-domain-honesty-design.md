---
title: "P1 — Domain honesty (Event ADT, ResolvedConfig, BlockReason, TicketState v2)"
type: spec
status: Executed
owner: "@iorlas"
created: 2026-04-24
updated: 2026-04-24
rfc: "../../rfcs/0001-v1-scope.md"
pitch: "../../pitches/2026-04-23-v1-scope.md"
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (V1.0 slicing session 2026-04-23)"
---

# P1 — Domain honesty

## Goal

Land the pure-type foundation for every downstream phase: `Event` sum type,
`ResolvedConfig`, `BlockReason`, `TicketState` schema v2 (ADR-0005), and a
`ChildOutcome` stub. **No behavior change** — existing dispatch keeps running
on `PipelineEvent` and the current state shape. P2 onwards reads the new types.
Also land L2 contract tests for ADR-0005 invariants I1–I8 so the ADR can move
from Proposed to Accepted.

First migration-phase spec of the V1.0 release. Appetite: **3 days.**

## Non-goals

- **No dispatch rewire.** `pipeline/dispatch.py` keeps using `PipelineEvent`.
  Swapping routing to match on `Event` is P4's job (pipe-and-filter dispatch).
- **No handler extraction.** `StageHandler` Protocol lands in P2, not here.
- **No effects ADT.** That's P3.
- **No schema changes beyond ADR-0005.** N5 fields are present but stay empty;
  N2 parent-branch logic stays unwritten.
- **No Jira path exercise.** Types are host-agnostic; validation happens later.
- **No renames of existing modules.** P7 owns the final layout.

## Plan

Each step = one commit, TDD where sensible.

1. **Add `ChildOutcome` stub to `domain/models.py`.**
   Empty-fielded `BaseModel` with `extra="allow"`. N5 fills the fields later.
   *Done when:* `from a2sdlc.domain.models import ChildOutcome` resolves and
   round-trips an empty `{}` through `model_validate` + `model_dump_json`.

2. **L1 test for TicketState v2 round-trip.**
   Failing test: `TicketState` accepts and preserves `schema_version=2`,
   `parent_key`, `children`, `child_outcomes`, `revisions`, `engine_version`,
   `workflow_name`, `rate_limited_until`, and any unknown future field.

3. **Implement TicketState v2 fields** in `domain/models.py`.
   Add `model_config = ConfigDict(extra="allow")`. Add fields per ADR-0005 §
   Schema version 2. Defaults exactly as ADR specifies.
   *Done when:* step 2's test passes; mypy / pyright clean.

4. **Create `session/state_migrations.py`.**
   TDD pair: failing test for `migrate_v1_to_v2({"stage": "spec", "branch":
   "a2sdlc/FOO", "stage_run_id": "r1", "last_updated": "..."})` produces the
   v2-shape dict; then the impl. Trivially adds default fields.
   Also implement `StateSchemaTooNew` and `StateSchemaRegression` exceptions
   in `domain/exceptions.py`.
   *Done when:* migration roundtrip test passes; reader on v3 raises
   `StateSchemaTooNew` (tested).

5. **Route `StateManager.read_state()` through migrations.**
   Failing test: a `.a2sdlc/state.json` lacking `schema_version` reads as v2
   after migration; writing it back persists `schema_version: 2`. Implement
   the route.
   *Done when:* existing persisted state files in tests/fixtures remain
   readable and are upgraded on first read.

6. **L2 contract tests for invariants I1–I8** against
   `GitFileStateStorage`. One test per invariant, with failure-mode
   simulation. I1 (read-after-setup), I2 (no base-branch writes), I3
   (allowlisted paths in commit), I4 (base cleanup after merge), I5
   (`stage_run_id` uniqueness), I6 (CI-level concurrency — assert the
   implementation does not acquire its own lock), I7 (`schema_version`
   monotonic), I8 (read-modify-write safety documented in docstring +
   preserved on round-trip with `extra="allow"`).
   *Done when:* all 8 tests green; test names map 1:1 to ADR-0005 I1–I8.

7. **Create `domain/events.py` — Event sum type.**
   Pydantic discriminated union per RFC-0001 §Interfaces and architecture
   vision §7.2:
   ```python
   Event = Annotated[
       TicketClosedEvent | LabelTriggerEvent | FeedbackEvent
         | ProceedEvent | SkipEvent,
       Field(discriminator="kind"),
   ]
   ```
   Each variant is a `BaseModel` with a literal `kind` and the fields from
   the vision (ticket `key`, `stage`, `pr_number`, `source`, etc.).
   `FeedbackSource` is a new `StrEnum` in `domain/events.py`.
   L1 test: every variant round-trips through JSON discriminated-union
   parsing.
   *Done when:* `Event` importable, variants exhaustively tested, mypy clean.

8. **Adapter from `PipelineEvent` to `Event`.**
   Helper `pipeline_event_to_event(pe: PipelineEvent) -> Event` in a new
   `domain/events.py` section (no I/O, still pure). Covers the existing
   triangulation: `is_closed → TicketClosedEvent`; `trigger_stage is not
   None → LabelTriggerEvent`; `is_feedback → FeedbackEvent`;
   otherwise `ProceedEvent`.
   No call sites adopt it yet. This helper is what P4 will drop in.
   L1 tests: each of the four flag combinations maps to the expected variant.

9. **Create `domain/config_resolved.py` — ResolvedConfig.**
   Pure `BaseModel` holding the collapsed 5-layer config (defaults →
   project.stage_overrides → directive overrides → label overrides → env).
   No resolver implementation here — just the target shape, with per-stage
   sub-config, `GateConfig`, `base_branch`, `workflow_name`. The
   resolver itself lives in `config/loader.py` when P6 lands; this step only
   defines the type so the config layer has a destination.
   L1 test: round-trip through JSON; defaults materialize correctly.

10. **Create `domain/block_reason.py` — BlockReason sum type.**
    Collapses the reason strings currently scattered through
    `pipeline/dispatch.py`, `pipeline/breakers.py`, and
    `pipeline/preflight.py`. Variants (from code inspection):
    `NoTriggerLabel`, `CostCeilingExceeded`, `ReviewCyclesExceeded`,
    `MergeGateHuman`, `SpecGateHuman`, `BaseBranchMissing`,
    `StateSchemaTooNew`, `BlockedGeneric(message: str)`.
    Each variant exposes a `.as_comment()` method for the
    progress-comment subscriber to render. L1 tests for each variant's
    comment output.
    No call sites adopt it yet. P4 migrates gating to produce these.

11. **Module exports + import-linter pre-check.**
    Update `domain/__init__.py` to export new names. Run `make lint` to
    confirm new modules respect the existing domain-purity rule (no imports
    from other a2sdlc packages). Update the import-linter config if a new
    whitelist entry is needed for `domain/events.py` → `domain/models.py`.
    *Done when:* `make check` is green.

12. **Flip ADR-0005 to Accepted.**
    Edit frontmatter in `docs/adr/0005-ticket-state-schema-and-storage-invariants.md`
    from `status: Proposed` to `status: Accepted`. The I1–I8 tests from
    step 6 are the gate; once green, the ADR is earned.
    *Done when:* grep shows `status: Accepted` in the ADR file.

## File-level changes

| File | Change |
|---|---|
| `packages/engine/src/a2sdlc/domain/models.py` | Modified — `TicketState` gets `schema_version`, N2/N5 fields, observability fields, rate-limit field, `extra="allow"`. Add `ChildOutcome` stub. |
| `packages/engine/src/a2sdlc/domain/events.py` | **New** — `Event` sum type (discriminated union), `FeedbackSource` enum, `pipeline_event_to_event()` helper. |
| `packages/engine/src/a2sdlc/domain/config_resolved.py` | **New** — `ResolvedConfig` shape (type only). |
| `packages/engine/src/a2sdlc/domain/block_reason.py` | **New** — `BlockReason` sum type + `.as_comment()` per variant. |
| `packages/engine/src/a2sdlc/domain/exceptions.py` | Modified — add `StateSchemaTooNew`, `StateSchemaRegression`. |
| `packages/engine/src/a2sdlc/domain/__init__.py` | Modified — re-export new symbols. |
| `packages/engine/src/a2sdlc/session/state_migrations.py` | **New** — `migrate_v1_to_v2(data: dict) -> dict`. |
| `packages/engine/src/a2sdlc/session/state_manager.py` (wherever `StateManager` lives today) | Modified — `read_state()` routes through migrations; raises `StateSchemaTooNew` on future versions. |
| `tests/unit/domain/test_events.py` | **New** — variant round-trip + `pipeline_event_to_event()` mapping. |
| `tests/unit/domain/test_ticket_state_v2.py` | **New** — schema v2 round-trip with all new fields + unknown-field preservation. |
| `tests/unit/domain/test_block_reason.py` | **New** — per-variant comment rendering. |
| `tests/unit/domain/test_config_resolved.py` | **New** — defaults + round-trip. |
| `tests/unit/session/test_state_migrations.py` | **New** — v1→v2 migration + `StateSchemaTooNew` on v3. |
| `tests/contract/session/test_git_file_state_storage_invariants.py` | **New** — I1–I8, one test method per invariant. |
| `docs/adr/0005-ticket-state-schema-and-storage-invariants.md` | Modified — status: Proposed → Accepted. |
| `.importlinter` (or equivalent config) | Modified only if a new whitelist entry is required. |

## Test strategy

- **L1 Unit.** Primary coverage for this spec. Every new type has a round-trip
  test; every helper has a mapping test; every exception has a raise-site test.
  The `pipeline_event_to_event()` helper gets a truth-table test across the
  four flag combinations.
- **L2 Contract.** Eight new tests against `GitFileStateStorage` for ADR-0005
  invariants I1–I8. Fake `StateStorage` impl must pass the same suite (per
  architecture vision §13.3 — "if the fake passes a test the real fails, the
  fake is wrong").
- **L3 Integration (fakes).** Existing dispatch tests must stay green — no
  behavior change. If they break, the P1 changes leaked outside the no-call-site
  rule; revert the leak.
- **L4 Real-platform.** No change. GH cassette tier keeps running unchanged.
- **L5 Event replay.** No change. The `Event` ADT is not yet routed through
  `parse_event`; the corpus comes online in P2/P4.
- **L6 E2E smoke.** No change. P1 ships no user-visible behavior.
- **L7 Eval.** Not applicable — no AI-touching code.

## Security considerations

- **Tokens / secrets touched:** none.
- **New external API calls:** none.
- **Data sensitivity:** `TicketState` schema is already serialized to the
  ticket branch as `state.json`. Adding `engine_version` + `workflow_name`
  fields does not change the sensitivity class (still no tokens, still no
  PII). `rate_limited_until` is an ISO timestamp — benign.
- **Abuse modes / input-trust assumptions:** state files on the ticket branch
  are writable by anyone who can push to the branch. This is already the case.
  `extra="allow"` preserves unknown fields on round-trip but does not
  **execute** them — no deserialization-to-code path. I3 (allowlisted commit
  paths) is now L2-enforced, closing the "attacker crafts unexpected files
  in `.a2sdlc/`" vector against future refactors that might drop the allowlist.

No new security surface beyond what already existed.

## Rollout

Single commit per step. Not feature-flagged — the types are additive and
unused by call sites until P2+. Merge to the V1.0 refactor branch as each
step lands.

Existing state files on the wire (any branch with a `.a2sdlc/state.json`
written pre-migration) upgrade **on first read** via `migrate_v1_to_v2` in
step 5. No batch migration needed; no coordination with consumer repos
required. The v1-reader / v2-reader boundary is forward-compatible because
v1 state files lack `schema_version` → treated as v1 → migrated → written
back as v2 on next state write.

**Deploy ordering:** once a writer is pushing v2 files, older engine versions
cannot read them (per ADR-0005 §Versioning rule 3). For V1.0 pre-release this
is irrelevant — the refactor branch is the only writer — but the CHANGELOG
note for V1.0 release must call it out so downstream consumers don't
roll back to a pre-V1.0 engine after state.json has been upgraded on their
branches.

## Backout

Fully revertible per step. Each commit is a type-addition; reverting does not
break any call site because no call site adopts the new types in P1.

The only non-trivial backout is step 5 (state migration routing): if a state
file has been read+upgraded+written-back to v2, a pre-P1 engine will silently
accept it (Pydantic ignores unknown fields by default) but will write it back
as v1, dropping the v2 fields. That's acceptable — the fields are empty in
V1.0 anyway. Document this in the commit body for step 5.

Step 12 (flipping ADR-0005 to Accepted) is trivially reverted by flipping the
frontmatter back.

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Pitch: [../../pitches/2026-04-23-v1-scope.md](../../pitches/2026-04-23-v1-scope.md)
- ADR-0005 (the contract this spec implements):
  [../../adr/0005-ticket-state-schema-and-storage-invariants.md](../../adr/0005-ticket-state-schema-and-storage-invariants.md)
- Architecture vision §7.2 (load-bearing types) and §10 (P1 phase summary):
  [../../vision/02-architecture-vision.md](../../vision/02-architecture-vision.md)
- Eval plan: none (not AI-touching).
- Next spec: P2 — Stage handlers + N1 inline review.
