---
title: "P2 — Stage handlers + N1 inline review"
type: spec
status: Draft
owner: "@iorlas"
created: 2026-04-24
updated: 2026-04-24
rfc: "../../rfcs/0001-v1-scope.md"
pitch: "../../pitches/2026-04-23-v1-scope.md"
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (V1.0 execution session 2026-04-24)"
---

# P2 — Stage handlers + N1 inline review

## Goal

Promote the four stage classes from thin config objects to full
`StageHandler`s (architecture vision §7.2). MERGE becomes a regular
handler — no more dispatch-level special casing. The REVIEW handler
gets the new N1 inline-comment capability end-to-end (adapter method,
domain type, effect stub). Add `SessionStorage` Protocol alongside
`StateStorage` (architecture vision Q7) so H2 external session storage
has its seam. Add L2 contract tests covering the N6 architectural
constraint — every handler is callable standalone without prior-stage
on-disk artifacts.

**P2 does NOT move side-effect emission into a pure `effects()` method.**
That's P3's job (effects ADT + interpreter). In P2, handlers still call
adapters directly from `execute()`; `effects()` returns an empty list.
The shape lands; the behavior shift comes next.

Second V1.0 migration-phase spec. Appetite: **1 week.**

## Non-goals

- **No effects ADT.** P3 defines the Effect sum type and moves side-effect
  emission out of `execute()` into `effects()`. P2's `effects()` is a
  no-op signature.
- **No pipeline/dispatch rewrite.** `pipeline/dispatch.py` keeps its
  current shape; only the stage-dispatch branch changes to call
  `handler.execute()` instead of `execute_ai_stage()` / `execute_merge()`.
- **No Jira-side exercise of N1.** Inline comments are GitHub-specific
  today (GitLab has equivalent API but no adapter in V1.0).
  `LocalNoopReviewAdapter` gets a no-op `post_inline_comments`.
- **No SessionStorage migration from disk.** We add the Protocol + a
  `LocalDiskSessionStorage` pass-through. Remote impls are H2.
- **No renames of existing modules.** P7 owns the final layout.
- **No adoption of the P1 types (Event ADT, ResolvedConfig, BlockReason)
  in call sites.** Those stay waiting for P4/P6.

## Plan

Each step = one commit. 11 steps grouped into 4 stages.

### A. Pure additions (safe, land first)

1. **`StageOutcome` + `InlineComment` domain types.**
   `StageOutcome` = structured result of a handler's execute(): `status`,
   `output_text`, `inline_comments: list[InlineComment]`, `stats`,
   `next_stage_hint`. `InlineComment(file, line_start, line_end, body,
   side)` is the review payload.
   *Location:* `domain/stage_outcome.py` (new file). L1 tests for
   construction + round-trip.

2. **`StageHandler` Protocol + `StageHandlerError`.**
   Protocol with `name`, `valid_statuses`, `preconditions(ctx)`,
   `execute(ctx) -> StageOutcome`, `effects(ctx, outcome) -> list[Effect]`.
   `effects()` return type is `list[object]` in P2 — P3 swaps in the
   real Effect ADT via a rename.
   *Location:* `stages/handler.py` (new file). L1 test: asserting the
   Protocol shape + that a minimal fake implements it.

3. **`SessionStorage` Protocol + `LocalDiskSessionStorage`.**
   Closes Q7. Protocol mirrors `StateStorage`: `save(session_id, bytes)`,
   `load(session_id) -> bytes | None`, `purge(session_id)`. Default
   impl is a thin pass-through around the SDK's on-disk session directory
   — zero behavior change today, infrastructure for H2.
   *Location:* `lifecycle/session_storage.py` (new file). L2 contract
   test with a fake impl.

4. **`InlineComment` added to `ReviewAdapter` Protocol (method stub).**
   Add `post_inline_comments(pr_number, comments: list[InlineComment]) -> None`
   to the Protocol. `LocalNoopReviewAdapter` gets a no-op impl. `GitHubReviewAdapter`
   gets a full impl using PyGithub's `create_review` with comments.
   *Contract test:* both impls accept an empty list without error.
   *L4 / cassette test:* a recorded cassette of a real GitHub inline-
   comment review proves the happy path.

### B. Handler shape migration (pair-by-pair, keep green)

5. **`SpecStage` becomes a `StageHandler`.**
   Move the SPEC-specific prompt assembly bits + adapter calls from
   `pipeline/stage_run.py::execute_ai_stage` (the SPEC-branch of it)
   into `SpecStage.execute()`. Non-SPEC branches stay in `execute_ai_stage`
   during this step — the dispatch branches on stage, and only the SPEC
   branch calls the new handler.
   *Contract test:* `SpecStage.execute()` callable standalone — given
   a fake ctx with fake adapters, it completes.
   *Integration test:* existing SPEC-path tests still pass.

6. **`ImplementStage` + `ReviewStage` become `StageHandler`s.**
   Same migration. `ReviewStage.execute()` additionally produces
   `StageOutcome.inline_comments` when the agent output contains them;
   `post_inline_comments` is called when the list is non-empty.
   At this point `execute_ai_stage()` is down to its IMPLEMENT / REVIEW
   glue and will be deleted in step 8.

7. **N1 wiring: agent output → `InlineComment` parser.**
   The REVIEW agent's structured output format gains an optional
   `inline_comments` field alongside `status`. Extend `StageResult`
   parsing in `domain/models.py::extract_result` or produce a separate
   `extract_inline_comments()` helper. L1 tests for parsing: missing
   field = empty list; malformed entries dropped with a warning, not
   a fatal.

8. **`MergeStage` becomes a `StageHandler`.**
   Port `pipeline/merge_flow.py::execute_merge` into `MergeStage.execute()`.
   MergeStage.`valid_statuses` stays empty (no AI status). `execute()`
   returns a `StageOutcome` with `status=None` and a `merged: bool`
   discriminator flag.
   *Cleanup:* delete `pipeline/merge_flow.py` and `pipeline/stage_run.py`
   once both are emptied. Their tests migrate to each handler's test
   file.
   *Integration test:* MERGE happy path, MERGE + human-gate path,
   MERGE + no-PR path — all now test `MergeStage.execute()` directly.

9. **Dispatch calls handlers uniformly.**
   `pipeline/dispatch.py` loses its `if target_stage == MERGE: ... else:`
   branch. One call shape:
   ```python
   handler = STAGES[target_stage]()
   outcome = await handler.execute(dispatch_ctx)
   ```
   `STAGES` registry in `stages/__init__.py` returns handler instances
   directly (no more `get_stage()` factory returning config objects).
   *Integration test:* existing `tests/integration/test_dispatch_*.py`
   stay green.

### C. Contract tests for N6 architectural constraint

10. **L2 standalone-invocability test per handler.**
    One test per handler that instantiates it, builds a minimal
    `RunContext` with fake adapters, calls `execute()`, asserts a
    `StageOutcome` is returned. Proves handlers carry no implicit
    prior-stage dependency. This is the RFC-0001 N6-architectural
    assertion.

### D. Closure

11. **Update P2 spec status to Executed. RFC-0001 + pitch stay.**

## File-level changes

| File | Change |
|---|---|
| `packages/engine/src/a2sdlc/domain/stage_outcome.py` | **New** — `StageOutcome`, `InlineComment`. |
| `packages/engine/src/a2sdlc/stages/handler.py` | **New** — `StageHandler` Protocol. |
| `packages/engine/src/a2sdlc/stages/spec.py` | Modified — add `execute()`, `preconditions()`, `effects()`. Absorb SPEC glue from `execute_ai_stage`. |
| `packages/engine/src/a2sdlc/stages/implement.py` | Modified — same, for IMPLEMENT. |
| `packages/engine/src/a2sdlc/stages/review.py` | Modified — same, for REVIEW; add inline-comment emission. |
| `packages/engine/src/a2sdlc/stages/merge.py` | Modified — absorb `execute_merge`. |
| `packages/engine/src/a2sdlc/stages/__init__.py` | Modified — `STAGES` holds instances (or classes with factory), exposed uniformly. |
| `packages/engine/src/a2sdlc/lifecycle/session_storage.py` | **New** — Protocol + `LocalDiskSessionStorage`. |
| `packages/engine/src/a2sdlc/adapters/review/__init__.py` | Modified — `post_inline_comments` on Protocol. |
| `packages/engine/src/a2sdlc/adapters/review/github.py` | Modified — implement `post_inline_comments`. |
| `packages/engine/src/a2sdlc/adapters/review/local_noop.py` | Modified — no-op `post_inline_comments`. |
| `packages/engine/src/a2sdlc/domain/models.py` | Modified — optional `inline_comments` in `StageResult` or alongside. |
| `packages/engine/src/a2sdlc/pipeline/dispatch.py` | Modified — uniform handler dispatch. |
| `packages/engine/src/a2sdlc/pipeline/stage_run.py` | **Deleted** (logic migrated to handlers). |
| `packages/engine/src/a2sdlc/pipeline/merge_flow.py` | **Deleted** (logic migrated to `MergeStage`). |
| `tests/domain/test_stage_outcome.py` | **New** — L1 tests for the domain type. |
| `tests/stages/test_*.py` | **New files** per handler — contract + unit tests. Migrate relevant tests from `tests/pipeline/`. |
| `tests/lifecycle/test_session_storage.py` | **New** — L2 contract tests. |
| `tests/adapters/review/test_inline_comments.py` | **New** — fake + real (cassette). |

## Test strategy

- **L1 Unit.** Every new type + every handler's `preconditions()` and
  `effects()` (pure). Parser for `inline_comments` in agent output.
- **L2 Contract.** One conformance suite for `StageHandler` — all 4
  handlers run through it + a fake. N6 standalone-invocability test
  per handler. New `SessionStorage` conformance. `ReviewAdapter`
  Protocol re-conformed (fake + real for `post_inline_comments`).
- **L3 Integration.** Existing dispatch integration tests stay green.
  New test: REVIEW path produces line-level comments via fake adapter.
- **L4 Real-platform.** New cassette for GitHub `create_review with
  comments` — record once against `iorlas/a2sdlc-smoke`, replay in CI.
- **L5 Event replay.** No change — event parsing untouched.
- **L6 E2E smoke.** The smoke workflow now asserts that a REVIEW cycle
  produces at least one inline comment when the agent output contains
  a valid comment block. Sanity check, not a precision assertion.
- **L7 Eval.** Not yet — P2 ships the REVIEW output *shape* change, not
  a prompt change. L7 pilot on SPEC (per RFC-0001) lands later.

## Security considerations

- **Tokens / secrets touched:** none new. `post_inline_comments` uses
  the reviewer App's installation token (N8 plumbing is P6; P2 still
  uses the existing single-token path).
- **New external API calls:** GitHub's `POST /repos/.../pulls/{n}/reviews`
  with comments array. Already used today by `post_review`; the comments
  array is the incremental surface.
- **Data sensitivity:** agent-produced review text goes into public PR
  comments. No tokens, no PII. Same sensitivity class as `post_review`.
- **Abuse modes:** a malicious ticket body could try to produce
  inline-comment payloads targeting files outside the PR diff. The
  adapter **must validate** `file` paths against the PR's diff file
  list before submitting. Add this guard with a dedicated L1 test.
  (This is in the N9 interim-posture spirit — tool-level output
  validation, not prompt-injection defense.)
- **Defaults:** empty `inline_comments` is a valid outcome. Missing
  field = empty list. No silent inline-comment posting without an
  explicit block.

## Rollout

Ships on the V1.0 refactor branch one step at a time. After step 9
(dispatch migration), the old `execute_ai_stage` / `execute_merge`
functions are gone — that is the load-bearing point where regressions
are likeliest. Run the full pytest suite + the cassette-replay
integration tier after step 9 before proceeding to step 10.

Not feature-flagged — the handler migration is structural.

## Backout

Steps A (1–4) are pure additions; trivially revertible. Steps B (5–9)
migrate behavior; each step ships with its own tests passing, so
reverting one step keeps the previous green. Step 9 (dispatch
migration) is the hardest to back out because it deletes the old
entry points; if it ships broken, revert the commit and the prior
state is clean (the handler classes still exist but are unused).

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Pitch: [../../pitches/2026-04-23-v1-scope.md](../../pitches/2026-04-23-v1-scope.md)
- Prior spec (P1): [2026-04-24-p1-domain-honesty-design.md](2026-04-24-p1-domain-honesty-design.md)
- Architecture vision §7.2 (StageHandler + Effect types), §2.17 (inline
  PR code review), §Q7 (SessionStorage Protocol), §2.21a (standalone
  execution).
- Eval plan: none (P2 doesn't change prompts).
- Next spec: P3 — Effects ADT + interpreter + N4 secrets-scan partial.
