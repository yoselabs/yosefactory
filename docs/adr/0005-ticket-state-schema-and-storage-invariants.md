---
title: "TicketState schema, versioning, and storage invariants"
type: adr
number: 0005
status: Proposed
owner: "@iorlas"
created: 2026-04-22
updated: 2026-04-22
rfc: null
supersedes: null
superseded_by: null
---

# ADR-0005 — TicketState schema, versioning, and storage invariants

- ![img](./static/media/icon.06a6aa23.png)**Status:** Proposed
- **Date:** 2026-04-22

## Context

`TicketState` is the engine's ledger per ticket. It is persisted today as `.a2sdlc/state.json` on the ticket branch, read at the start of every stage, written at the end, committed and pushed. It is the single source of truth for stage status, review cycles, accumulated cost, PR number, and (soon) parent/child epic relationships.

Three forces make its shape load-bearing:

1. **Near-term N2** (subtask-driven execution, architecture vision §2.18) adds `parent_key` and `children` fields. Hierarchical branches branch off a parent branch; parent state must enumerate its children.
2. **Near-term N5** (backpropagation, §2.21) adds `child_outcomes` dict and `revisions` counter. Requires durable append-only history per parent.
3. **Horizon H2** (external session / state storage) eventually moves the persistence layer from branch-`state.json` to an external KV (Redis / Postgres). `StateStorage` Protocol already abstracts this, but the *schema* has never been versioned — an external backend cannot migrate old rows without a version tag.

Two production failure modes have already shipped fixes that landed without explicit invariants, and without ADR coverage:

- **State leaking to base on squash-merge** (commit `24abaf8`) — `.a2sdlc/state.json` appeared on `main` after PR merge because the file was committed to the ticket branch and squash-merged with the rest of the branch content. Fix: cleanup after merge.
- **State read before branch setup** (commit `a78b404`) — dispatch tried to read state before `git.setup_branch()` checked the branch out, so it read from whatever branch was ambient. Fix: reorder.

Both fixes are invariants that today live only in commit messages and the position of function calls in `pipeline/dispatch.py`. A future refactor can easily re-break them if the invariants are not declared.

## Decision

Adopt a **versioned `TicketState` schema with explicit invariants** before any N-item touches the state model.

### Schema version 2 — adopted now, one migration ahead of where we need it

`TicketState` gets a `schema_version: int` field. Current code reads/writes schema version **2**. Version 1 is the implicit current shape (no version field).

```python
class TicketState(BaseModel):
    model_config = ConfigDict(extra="allow")  # preserve unknown fields round-trip

    schema_version: int = 2

    # v1 fields — unchanged semantics
    stage: StageName
    status: StageStatus | None = None
    base_branch: str = "main"
    branch: str
    pr_number: int | None = None
    stage_run_id: str
    review_cycles: int = 0
    accumulated_cost_usd: float = 0.0
    accumulated_tokens_in: int = 0
    accumulated_tokens_out: int = 0
    accumulated_duration_ms: int = 0
    last_updated: str

    # v2 additions (N2 unblock)
    parent_key: str | None = None          # parent ticket key for child stories
    children: list[str] = Field(default_factory=list)  # child ticket keys when this is an epic
    child_outcomes: dict[str, ChildOutcome] = Field(default_factory=dict)  # N5 placeholder, populated later
    revisions: int = 0                     # N5 placeholder, incremented on drift-triggered re-spec

    # Observability / reproducibility
    engine_version: str = ""               # semver + git SHA of engine that last wrote this state
    workflow_name: str = "default"         # which declarative workflow config was used

    # Rate-limiting self-heal (§2.23)
    rate_limited_until: str | None = None  # ISO timestamp; scheduled sweep re-dispatches after this
```

### Versioning rules

1. **`schema_version` is an integer** incremented on any field addition, removal, rename, or semantic change.
2. **Forward compatibility is guaranteed** — a reader on version N+1 must handle a document written at version N by applying a named migration function. Migration functions live in `a2sdlc/session/state_migrations.py` as `migrate_vN_to_vNplus1(data: dict) -> dict`.
3. **Backward compatibility is NOT guaranteed** — a v2 reader may not read v3 documents. Attempting to read a newer version raises `StateSchemaTooNew` (a permanent error, not retryable).
4. **Unknown fields are preserved on round-trip** (`extra="allow"` + round-trip writeback). Protects forward compatibility when older engines read newer state in edge cases.
5. **Version bumps are ADR-worthy.** Each bump gets its own ADR describing the migration and the reason.

### Storage invariants — declared, enforced by tests

These invariants were implicit; they are now explicit and L2-contract-test-enforced.

| # | Invariant | Why |
|---|---|---|
| I1 | **State is read only after `git.setup_branch()` has succeeded.** The branch must be checked out before the file path is valid. | Prevents ambient-branch reads (the `a78b404` bug). |
| I2 | **State is written on the ticket branch, never on the base branch.** Before any write, assert current branch matches `state.branch`. | Prevents state leaking to `main` on squash-merge (the `24abaf8` bug). |
| I3 | **State writes are followed by commit + push of only allowlisted paths** (`.a2sdlc/state.json`, `docs/`). Runtime artifacts (`.a2sdlc/logs/`, session files) must NOT be committed. | Prevents runtime noise leaking cross-stage. |
| I4 | **Base branch cleanup runs after merge** to remove per-ticket artifacts that the squash carried across. Idempotent. | Second half of the fix for I2. |
| I5 | **`stage_run_id` is unique per dispatch invocation** (deterministic derivation per composition profile, see existing `_derive_mode2_run_id`). Idempotency middleware keys on this. | Prevents duplicate event delivery from re-running stages. |
| I6 | **Concurrent writes to the same ticket state are serialized by CI-level concurrency group**, not by in-engine locking. If two dispatches race past the CI gate, idempotency middleware (I5) detects and skips the second. | Declares the concurrency model so future engine work doesn't invent a lock. |
| I7 | **`schema_version` monotonically increases within a ticket's lifetime.** Downgrades are not supported; attempting to write an older schema over a newer one raises `StateSchemaRegression`. | Forces clean upgrade paths; catches deployment mistakes. |
| I8 | **`StateStorage` implementations must be read-modify-write safe** — the interface does not promise atomicity, but each impl must document its consistency model. Git-backed today (branch push + rebase as the serialization); external KV later (conditional writes or row locks). | Names the abstraction seam for H2. |

### StateStorage Protocol remains the abstraction seam

Already exists in `lifecycle/state_storage.py`. Unchanged in this ADR. Reaffirmed as the sole boundary between the domain model and the persistence mechanism. Adding N2 fields does not change the Protocol; adding H2 external storage will not change the Protocol.

## Consequences

**Positive:**
- N2 (subtask execution) can land without inventing a state shape ad-hoc.
- N5 (backpropagation) has the fields reserved for it, so the second schema bump for N5 is minimal.
- H2 (external session / state storage) has a version tag to migrate against — without it, a future external backend would face an un-versioned corpus of JSON blobs.
- Production failure modes (the two fixed) are no longer invisible — any future refactor violates a named, test-enforced invariant.
- `schema_version: int = 2` with migrations is a 6-month-hardened pattern (the same shape as Django migrations, Flyway, etc.); no novel cleverness.

**Negative:**
- Every field change now requires an ADR + a migration function. Slower than "just add a field."
- Pydantic `extra="allow"` + round-trip preservation adds minor cognitive overhead (read-modify-write pattern must be honored).
- Backward-incompatibility (v2 reader can't read v3) means deploy ordering matters — rolling out a v3 writer before a v3 reader breaks old readers. Naming this in the release checklist is required.

**Neutral:**
- `child_outcomes` and `revisions` fields land empty until N5 — small disk cost per state.json, acceptable.

## Alternatives considered

- **No version field, handle shape changes in Pydantic defaults.** Rejected: silently breaks when a v1 reader meets a v2 document with a field Pydantic can't default. Already caused one surprise when `base_branch` was added without a default.
- **Date-based version (YYYY-MM-DD).** Rejected: ordering is unambiguous with integers; date versions suggest chronology irrelevant to schema shape. Integers force the question "what's different in v3 vs v2?" in ADRs.
- **Store version in file name (`state.v2.json`).** Rejected: state file path is referenced in many places; renaming the file breaks every read. In-document version is cheaper.
- **Defer version field until H2 actually needs it.** Rejected: retrofitting a version field onto an un-versioned corpus is exactly the migration we would then face. Pay the cost once, now.
- **Use Pydantic's `discriminator` with a sum type.** Rejected: overkill for a single-document schema evolution; the migration-function pattern is clearer and handles broader shape changes (removed fields, renames) more naturally.

## Implementation notes

1. Add `schema_version: int = 2` to `TicketState` in `domain/models.py`.
2. Add `parent_key`, `children`, `child_outcomes`, `revisions` fields. Use `Field(default_factory=...)` for mutable defaults.
3. Create `session/state_migrations.py` with `migrate_v1_to_v2(data: dict) -> dict` — trivially adds the new fields with defaults.
4. Modify `StateManager.read_state()` to route through migrations when `schema_version` is missing or less than the current version. On schema version greater than current, raise `StateSchemaTooNew`.
5. Add L2 contract tests for I1–I8 against `GitFileStateStorage`. Tests must pass before the ADR moves from Proposed to Accepted.
6. Add a stub `ChildOutcome` model in `domain/models.py` so N5 has a forward placeholder — fields TBD by the N5 RFC.
7. Release note in `CHANGELOG.md`: "State file schema bumped to v2; older engines cannot read v2 state files."

## Related

- Architecture vision §2.6, §2.18, §2.21, §10 P1, §12 Q7 (SessionStorage Protocol).
- ADR-0001 (hexagonal-lite) — this ADR works within that layering.
- TODO.md fixes: `24abaf8` state-leaking-to-base, `a78b404` read-state-after-branch-setup.
- Future ADR-0006 (handler output is Temporal-ready) — will constrain effects to be serializable; state is already serializable by virtue of this ADR.
- Future N5 RFC will bump schema to v3 when `ChildOutcome` fields are finalized.
