# Engine Architecture v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the a2sdlc engine to fix 5 production bugs and support multiple ticket/code platforms via three-adapter architecture with TDD throughout.

**Architecture:** Three adapters (WorkAdapter, GitAdapter, ReviewAdapter) split by concern. Comment lifecycle owned by engine with begin/update/finalize contract. Follow-up prompt pattern for structured output. Gate system for human-in-the-loop control. Dispatch decomposed into focused modules (CommentManager, StageExecutor, StateManager, PRLifecycle).

**Tech Stack:** Python 3.12, Pydantic 2, claude-agent-sdk, tenacity (new), gitpython, PyGithub

**Spec:** `docs/superpowers/specs/2026-04-12-engine-architecture-v2-design.md`

**TDD rule:** Every task follows red-green-refactor. Write failing test first, implement minimum to pass, refactor. No code without a failing test. Run `make lint` after each task.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/a2sdlc/directives.py` | Ticket directive parsing (`[a2sdlc ...]` syntax) |
| `src/a2sdlc/stats.py` | StageRunStats accumulator |
| `src/a2sdlc/comment_lifecycle.py` | CommentManager — owns comment_id, begin/update/finalize |
| `src/a2sdlc/stage_executor.py` | Run stage + follow-up prompt + stats accumulation |
| `src/a2sdlc/state_manager.py` | Read/write TicketState, idempotency, session ID |
| `src/a2sdlc/pr_lifecycle.py` | Draft PR creation, update, merge gate |
| `src/a2sdlc/adapters/work.py` | WorkAdapter protocol + PipelineEvent |
| `src/a2sdlc/adapters/review.py` | ReviewAdapter protocol + Approval/ReviewComment types |
| `src/a2sdlc/adapters/retry.py` | Tenacity retry wrappers for must-succeed calls |
| `tests/fakes_v2.py` | FakeWorkAdapter, FakeReviewAdapter, FakeGitAdapter, FakeRunner |

### Modified Files

| File | Changes |
|------|---------|
| `src/a2sdlc/exceptions.py` | Add AdapterError hierarchy (RetryableError, PermanentError, etc.) |
| `src/a2sdlc/models.py` | Add TicketState, GateMode, GateConfig. Keep BranchState as alias until cleanup. |
| `src/a2sdlc/config.py` | Add gate_config() to ProjectConfig, update session ID with review_cycles |
| `src/a2sdlc/dispatch.py` | Thin orchestrator composing CommentManager + StageExecutor + StateManager + PRLifecycle |
| `src/a2sdlc/adapters/protocols.py` | Update GitAdapter.setup_branch signature (branch_name, not key) |
| `src/a2sdlc/stages/__init__.py` | Update next_stage to accept GateConfig instead of PipelineFlags |
| `src/a2sdlc/prompts/stages/implement.md` | Add skill scoping: "DO NOT invoke brainstorming" |
| `src/a2sdlc/prompts/stages/review.md` | Add skill scoping: "DO NOT invoke brainstorming or writing-plans" |
| `src/a2sdlc/progress.py` | Update format_final to include task summary in collapsed block |
| `pyproject.toml` | Add tenacity dependency |

---

## Phase 1: Foundation (Tasks 1-7)

Independent modules. No behavior change to existing code. Each task produces a self-contained, tested module.

---

### Task 1: Exception Taxonomy

**Goal:** Extend exception hierarchy for adapter error classification and retry logic.

**Files:** `src/a2sdlc/exceptions.py`, `tests/test_exceptions_v2.py`

**Requirements:**
- Add `AdapterError` base class (NOT related to `SkipEvent` — `SkipEvent` remains a standalone pipeline control signal)
- Add `RetryableError(AdapterError)` and `PermanentError(AdapterError)` as two branches
- `RetryableError` subtypes: `RateLimitError` (with `retry_after: float` attribute, default 0.0), `TransientError`
- `PermanentError` subtypes: `AuthError`, `NotFoundError`, `PlatformValidationError`
- `BlockedError` becomes a subclass of `PermanentError` (keep its `reason` attribute)
- All existing imports of `BlockedError` and `SkipEvent` must continue to work

**Tests to write:**
- Verify full hierarchy: `issubclass` checks for every exception type
- `RateLimitError` stores and defaults `retry_after`
- `SkipEvent` is NOT an `AdapterError`
- `BlockedError` IS a `PermanentError` and retains `reason`

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement exception hierarchy
- [ ] Run tests — verify PASS
- [ ] Run `make lint`
- [ ] Commit

---

### Task 2: Core Models — TicketState, GateMode, GateConfig

**Goal:** Add new Pydantic models for v2 state management and gate system.

**Files:** `src/a2sdlc/models.py`, `tests/test_models.py`

**Requirements:**
- `GateMode(StrEnum)`: values `"auto"`, `"human"`
- `GateConfig(BaseModel)`: fields `merge: GateMode = GateMode.HUMAN`, `review: GateMode = GateMode.AUTO`
- `TicketState(BaseModel)`: fields `stage`, `status` (optional), `base_branch` (default "main"), `branch`, `pr_number` (optional), `stage_run_id`, `comment_id` (optional), `review_cycles` (default 0), `accumulated_cost_usd` (default 0.0), `accumulated_tokens_in` (default 0), `accumulated_tokens_out` (default 0), `accumulated_duration_ms` (default 0), `last_updated`
- Keep `BranchState` as an alias: `BranchState = TicketState` — do NOT remove or replace usages yet
- Extend `StageResult` with optional fields: `pr_title`, `pr_summary`, `ticket_summary`, `spec_path`, `plan_path`, `questions` (list[str]). All optional, default None. `extract_result` should parse them from JSON (Pydantic handles this automatically if fields are added to the model).

**Tests to write:**
- `GateMode` enum values and string parsing
- `GateConfig` defaults (merge=HUMAN, review=AUTO) and overrides
- `TicketState` JSON roundtrip, default values
- `StageResult` with new optional fields parses correctly
- `extract_result` works with new fields present and absent

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement models
- [ ] Run tests — verify PASS
- [ ] Run full suite (`uv run pytest tests/`) — verify no regressions
- [ ] Commit

---

### Task 3: StageRunStats Accumulator

**Goal:** Accumulator for cost/tokens/duration across retries within a stage run.

**Files:** `src/a2sdlc/stats.py`, `tests/test_stats.py`

**Requirements:**
- `StageRunStats` dataclass with fields: `cost_usd`, `tokens_in`, `tokens_out`, `duration_ms`, `num_turns` — all default 0
- `add_from_result(result: RunResult)` method that sums all fields from a `RunResult` into the accumulator. Import `RunResult` from `a2sdlc.runner`.
- `reset()` method that zeros all fields

**Tests to write:**
- Defaults are zero
- `add_from_result` with a RunResult adds correctly
- Multiple `add_from_result` calls accumulate
- `reset` zeros everything

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 4: Ticket Directive Parsing

**Goal:** Parse `[a2sdlc key=value]` directives from ticket descriptions and strip them from body.

**Files:** `src/a2sdlc/directives.py`, `tests/test_directives.py`

**Requirements:**
- `TicketDirectives(BaseModel)`: fields `base` (optional str), `gate_merge` (optional GateMode), `gate_review` (optional GateMode), `model` (optional str)
- `parse_directives(body: str) -> tuple[TicketDirectives, str]`: extracts all `[a2sdlc ...]` lines from body, returns (directives, cleaned_body)
- Syntax: `[a2sdlc base=feature/x gate:merge=human model=opus]` — space-separated key=value pairs, colons in keys supported
- Multiple directive lines supported (merged)
- Malformed directives (empty brackets, invalid gate values) silently ignored — no crash
- Cleaned body has directive lines removed, whitespace trimmed

**Tests to write:**
- No directives → empty directives, body unchanged
- Single directive with base override
- Gate directive parsing (gate:merge=human)
- Multiple directives on one line
- Multiple directive lines
- Malformed directive ignored
- Body content preserved after stripping
- Empty body → no crash

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 5: Adapter Protocols — WorkAdapter, ReviewAdapter

**Goal:** Define the new adapter protocols and update GitAdapter signature.

**Files:** `src/a2sdlc/adapters/work.py`, `src/a2sdlc/adapters/review.py`, `src/a2sdlc/adapters/protocols.py`, `src/a2sdlc/adapters/__init__.py`

**Requirements:**

**PipelineEvent** (in `work.py`): replaces `DispatchInput`. Fields: `key: str`, `stage: StageName`, `is_resume: bool = False`, `pr_number: int | None = None`. Simple class (not frozen dataclass — needs to be easy to construct in tests).

**WorkAdapter** (Protocol in `work.py`):
- `parse_event() -> PipelineEvent`
- `get_ticket(key: str) -> str`
- `get_labels(key: str) -> list[str]`
- `begin_comment(key: str) -> str` — creates comment, returns ID
- `update_progress(comment_id: str, body: str) -> None` — may debounce
- `finalize_comment(comment_id: str, body: str) -> None` — must flush
- `set_stage_label(key: str, stage: StageName) -> None`
- `set_done_label(key: str) -> None`
- `set_blocked(key: str, reason: str) -> None`
- `format_branch(ticket_key: str) -> str`

**ReviewAdapter** (Protocol in `review.py`):
- `create_draft_pr(branch: str, base: str, title: str, ticket_key: str) -> int`
- `update_pr(pr_number: int, title: str, body: str, ticket_key: str) -> None`
- `mark_pr_ready(pr_number: int) -> None`
- `merge_pr(pr_number: int, method: str = "squash") -> None`
- `get_approvals(pr_number: int) -> list[Approval]`
- `post_review(pr_number: int, body: str, verdict: str) -> None`
- `read_pr_diff(pr_number: int) -> str`
- `read_pr_comments(pr_number: int) -> list[ReviewComment]`

**Supporting types** (in `review.py`): `Approval(user: str, is_bot: bool)`, `ReviewComment(author: str, body: str, created_at: str)` — frozen dataclasses.

**GitAdapter** update in `protocols.py`: change `setup_branch(key: str, base: str)` to `setup_branch(branch_name: str, base: str)` — takes full branch name, doesn't generate it.

**`__init__.py`**: re-export all protocols and types.

**No tests for this task** — protocols are structural, tested via fakes in Task 6.

- [ ] Create `work.py` with PipelineEvent and WorkAdapter protocol
- [ ] Create `review.py` with types and ReviewAdapter protocol
- [ ] Update `protocols.py` — remove old TicketAdapter, update GitAdapter signature, keep StageRunner
- [ ] Update `__init__.py` exports
- [ ] Run `make lint`
- [ ] Commit

---

### Task 6: Fake Adapters v2

**Goal:** Test doubles implementing new protocols. These are test infrastructure — the quality of these fakes determines the quality of all integration tests.

**Files:** `tests/fakes_v2.py`, `tests/test_comment_lifecycle.py`

**Requirements:**

**FakeWorkAdapter:**
- Implements WorkAdapter protocol
- Records all calls in lists: `created_comments`, `progress_updates`, `finalized_comments`, `label_history`, `blocked`
- `begin_comment` returns unique IDs (e.g., `comment-1`, `comment-2`)
- `format_branch` returns `agent/{ticket_key}`
- Constructor accepts: `event`, `ticket_body`, `labels`

**FakeReviewAdapter:**
- Implements ReviewAdapter protocol
- Records: `created_prs`, `updated_prs`, `ready_prs`, `merged_prs`, `reviews`
- `create_draft_pr` returns incrementing PR numbers
- Constructor accepts: `pr_diff`, `pr_comments`, `approvals`

**FakeGitAdapter:**
- Same as current but `setup_branch(branch_name, base)` returns `branch_name` (not generated)
- Constructor accepts: `state_json`, `conflict_on_setup`

**FakeRunner:**
- Same as current but uses new `RunnerCall` dataclass (not prefixed with underscore)
- Accepts single or list of `RunResult` for sequential returns

**Comment lifecycle contract tests** (`test_comment_lifecycle.py`):
- `begin_comment` returns unique IDs across calls
- `update_progress` records (comment_id, body) pairs
- `finalize_comment` records (comment_id, body) pairs
- `format_branch` returns correct pattern
- Total comments created matches number of `begin_comment` calls

- [ ] Write comment lifecycle contract tests (RED)
- [ ] Run tests — verify FAIL
- [ ] Implement all fake adapters
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 7: Retry Wrappers with Tenacity

**Goal:** Retry decorator/wrapper for must-succeed adapter calls.

**Files:** `src/a2sdlc/adapters/retry.py`, `tests/test_retry.py`, `pyproject.toml`

**Requirements:**
- Add `tenacity>=8.0` to dependencies in `pyproject.toml`, run `uv sync`
- `must_succeed(fn, *args, **kwargs)` function that:
  - Retries on `RetryableError` with exponential backoff
  - Does NOT retry on `PermanentError` or other exceptions — re-raises immediately
  - Stops after `max_attempts` (default 5, configurable for tests)
  - Logs a structured WARNING on each retry (logger name: `a2sdlc.adapters.retry`)
  - Accepts `wait_multiplier` and `wait_max` kwargs for fast tests
  - Returns the function's return value on success
  - Re-raises the last exception after max attempts

**Tests to write:**
- Succeeds on first try — function called once
- Retries on `TransientError`, succeeds on 3rd attempt
- Raises immediately on `PermanentError` (e.g., `AuthError`) — no retry
- Raises after max attempts exhausted
- Each retry produces a log record (use `caplog`)

- [ ] Add tenacity to pyproject.toml and sync
- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement `must_succeed`
- [ ] Run tests — verify PASS
- [ ] Commit

---

## Phase 2: Config & Transitions (Tasks 8-10)

Update existing modules to use new models. Still no dispatch changes.

---

### Task 8: Config — GateConfig, Session ID

**Goal:** Update ProjectConfig to support gate configuration from YAML. Update session ID to include review_cycles.

**Files:** `src/a2sdlc/config.py`, `tests/test_config.py`

**Requirements:**

**Session ID update:**
- `get_session_id(ticket_key, stage, review_cycles=0)` — include review_cycles in the UUID seed so `changes_requested` loops get fresh sessions
- Backward compatible: default `review_cycles=0` produces same ID as before for spec/implement first runs

**ProjectConfig update:**
- Add `gate_config() -> GateConfig` method
- Parse `pipeline.gates.merge` and `pipeline.gates.review` from YAML (string values mapped to `GateMode` enum)
- Defaults: merge=HUMAN, review=AUTO (matching `GateConfig` defaults)
- Keep existing `auto_spec` field (it's a prompt modifier, not a gate)
- Remove `auto_proceed` and `auto_merge` fields — replaced by gates
- Remove `PipelineFlags` class and `resolve_flags` function — replaced by `GateConfig` + ticket directives
- Remove `_LABEL_FLAG_MAP` — labels replaced by directives

**Tests to write:**
- Session ID with different `review_cycles` produces different IDs
- Session ID with same params is deterministic
- `gate_config()` returns defaults when no gates in YAML
- `gate_config()` parses `merge: auto` from YAML
- Loading YAML without `pipeline.gates` section uses defaults

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement config changes
- [ ] Run tests — verify PASS
- [ ] Run full suite — some old tests may need updating (PipelineFlags removal)
- [ ] Commit

---

### Task 9: Stage Transitions — New Gate Model

**Goal:** Update stage transition table to use GateConfig instead of PipelineFlags.

**Files:** `src/a2sdlc/stages/__init__.py`, `src/a2sdlc/stages/spec.py`, `src/a2sdlc/stages/implement.py`, `src/a2sdlc/stages/review.py`, `tests/test_stages.py`

**Requirements:**

**Transition model update:**
- The `Gate` enum (`AUTO_PROCEED`, `AUTO_MERGE`) is replaced. Each `Transition` references a `GateConfig` field name (string) instead.
- Or simpler: remove `gate` from `Transition`, encode gate logic directly in `next_stage()`. The function checks `GateConfig` fields based on the stage+status combination.

**`next_stage(stage, status, gates: GateConfig) -> StageName | None`:**
- Spec + complete → always IMPLEMENT (no gate)
- Spec + questions → None (wait)
- Implement + complete + gates.review=AUTO → REVIEW
- Implement + complete + gates.review=HUMAN → None (wait)
- Implement + questions → None (wait)
- Review + approved + gates.merge=AUTO → MERGE
- Review + approved + gates.merge=HUMAN → None (wait)
- Review + changes_requested → always IMPLEMENT (no gate)

**Tests to write:**
- All 8 combinations above
- Delete or update old `TestNextStage` tests that use `PipelineFlags`
- Delete or update old `TestTransitionTable` tests that validate `Gate` enum references

- [ ] Write failing tests for new `next_stage` signature
- [ ] Run tests — verify FAIL
- [ ] Update stage files and `next_stage` function
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 10: Skill Scoping in Stage Prompts

**Goal:** Prevent brainstorming skill from being invoked in implement and review stages.

**Files:** `src/a2sdlc/prompts/stages/implement.md`, `src/a2sdlc/prompts/stages/review.md`

**Requirements:**

**implement.md** — Add a Context section near the top:
> "Brainstorming and design are COMPLETED. The spec and plan are in `docs/superpowers/`. Do NOT invoke the brainstorming skill — design decisions are already made. Focus on execution."

**review.md** — Add a Context section near the top:
> "This is an independent code review. Do NOT invoke brainstorming or writing-plans skills. Review the code on its merits."

**Tests:** Add assertions in `tests/test_cli.py` (or a new test) that the assembled system prompt for implement contains "DO NOT" and "brainstorming", and the review prompt contains similar. This catches accidental regression if prompts are edited.

- [ ] Update prompt files
- [ ] Write test asserting prompt content
- [ ] Run tests — verify PASS
- [ ] Commit

---

## Phase 3: Dispatch Decomposition (Tasks 11-15)

The dispatch module is split into four focused modules, each independently testable. Then dispatch.py becomes a thin orchestrator.

---

### Task 11: CommentManager

**Goal:** Encapsulate the comment lifecycle — one comment per stage run, no orphans.

**Files:** `src/a2sdlc/comment_lifecycle.py`, `tests/test_comment_manager.py`

**Requirements:**
- `CommentManager` class, initialized with a `WorkAdapter` and `ticket_key`
- `start(stage_name: str) -> None` — calls `work.begin_comment(key)`, stores `comment_id` internally
- `update(body: str) -> None` — calls `work.update_progress(comment_id, body)`. No-op if `start` hasn't been called.
- `finalize(body: str) -> None` — calls `work.finalize_comment(comment_id, body)` wrapped in `must_succeed` retry. Marks as finalized.
- `comment_id` property — returns current comment ID
- Calling `start()` again raises an error if previous comment wasn't finalized (prevents orphans by contract)
- Calling `finalize()` twice is a no-op (idempotent)

**Tests to write (using FakeWorkAdapter):**
- `start` creates one comment
- `update` forwards to adapter
- `finalize` forwards to adapter
- Cannot `start` new comment before finalizing previous (raises)
- Double `finalize` is no-op
- `update` before `start` is no-op
- `finalize` uses retry wrapper (mock adapter that fails once then succeeds)

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement CommentManager
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 12: StateManager

**Goal:** Read/write TicketState, generate session IDs, check idempotency.

**Files:** `src/a2sdlc/state_manager.py`, `tests/test_state_manager.py`

**Requirements:**
- `StateManager` class, initialized with a `GitAdapter`
- `read_state() -> TicketState | None` — reads from git adapter, parses YAML/JSON
- `write_state(state: TicketState) -> None` — serializes and writes via git adapter
- `check_idempotency(stage_run_id: str) -> bool` — returns True if the given run_id matches stored state (duplicate). Returns False if no state or different run_id.
- `generate_run_id() -> str` — reads from `GITHUB_RUN_ID` + `GITHUB_RUN_ATTEMPT` env vars if available, otherwise `A2SDLC_RUN_ID` env var, otherwise random UUID
- `get_session_id(ticket_key, stage, review_cycles) -> str` — delegates to `config.get_session_id`

**Tests to write (using FakeGitAdapter):**
- Read state when none exists returns None
- Read state parses stored JSON correctly
- Write state serializes and stores
- Idempotency check — matching run_id returns True
- Idempotency check — different run_id returns False
- Idempotency check — no prior state returns False
- Run ID generation from env vars (mock `os.environ`)
- Run ID generation fallback to UUID

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement StateManager
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 13: StageExecutor

**Goal:** Run a stage via the runner, handle follow-up prompts, accumulate stats.

**Files:** `src/a2sdlc/stage_executor.py`, `tests/test_stage_executor.py`

**Requirements:**
- `StageExecutor` class, initialized with a `StageRunner`
- `run(user_prompt, system_prompt, config, ticket_key, stage, project_root, is_resume, on_progress, branch) -> ExecutionResult`
- `ExecutionResult` dataclass: `output: str`, `stage_result: StageResult | None`, `stats: StageRunStats`, `success: bool`, `error: str | None`, `milestones: list`, `progress: ProgressState | None`
- After runner returns: check for `a2sdlc` status block in output
- If no status block: send follow-up prompt as session resume (`is_resume=True`). Follow-up template includes repo_url, branch, instructions to produce structured block. Retry follow-up up to 2 more times.
- If still no status block after 3 follow-up attempts: set `stage_result = None`, include partial output
- Stats accumulated across all runner calls (initial + follow-ups) via `StageRunStats.add_from_result`
- Auto-approve retry (the old mechanism) is replaced by the follow-up prompt pattern

**Tests to write (using FakeRunner):**
- Agent produces status block on first try → single runner call, correct stats
- Agent produces no status block → follow-up sent as resume, status block in second call
- Follow-up also fails → retried up to 3 times, then partial result
- Stats accumulated across initial call + follow-up calls
- Progress callback wired through to runner
- Follow-up prompt contains "handover" or "status" instruction

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement StageExecutor
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 14: PRLifecycle

**Goal:** Manage draft PR creation, updates, and merge gate.

**Files:** `src/a2sdlc/pr_lifecycle.py`, `tests/test_pr_lifecycle.py`

**Requirements:**
- `PRLifecycle` class, initialized with a `ReviewAdapter`
- `create_draft(branch, base, ticket_key) -> int` — creates draft PR with placeholder title, returns pr_number
- `update_from_result(pr_number, stage_result, ticket_key) -> None` — updates PR title and body from StageResult fields (pr_title, pr_summary). Wraps in `must_succeed`.
- `post_review(pr_number, body, verdict) -> None` — posts review on PR
- `check_human_approval(pr_number) -> bool` — checks `get_approvals`, returns True if at least one non-bot approval exists
- `merge(pr_number, method="squash") -> None` — marks PR ready, then merges. Both wrapped in `must_succeed`.
- `read_context(pr_number) -> str` — reads PR diff + comments, formats as context string for review stage user_prompt

**Tests to write (using FakeReviewAdapter):**
- `create_draft` creates PR with correct args
- `update_from_result` updates title and body from StageResult
- `check_human_approval` returns True when non-bot approval exists
- `check_human_approval` returns False when only bot approvals
- `check_human_approval` returns False when no approvals
- `merge` calls mark_ready then merge_pr
- `read_context` combines diff and comments

- [ ] Write failing tests
- [ ] Run tests — verify FAIL
- [ ] Implement PRLifecycle
- [ ] Run tests — verify PASS
- [ ] Commit

---

### Task 15: Dispatch v2 — Thin Orchestrator

**Goal:** Rewrite dispatch.py as a thin orchestrator composing CommentManager, StageExecutor, StateManager, and PRLifecycle.

**Files:** `src/a2sdlc/dispatch.py`, `tests/test_dispatch_v2.py`

**Requirements:**

**DispatchContext** dataclass:
- `work: WorkAdapter`
- `git: GitAdapter`
- `review: ReviewAdapter`
- `runner: StageRunner`
- `config: ProjectConfig`
- `project_root: Path`
- `logger: logging.Logger`

**`dispatch(ctx) -> DispatchResult`** flow:
1. `work.parse_event()` → PipelineEvent (handle SkipEvent)
2. Parse ticket directives from `work.get_ticket()` via `parse_directives()`
3. Merge directives with project config (directives override config defaults)
4. `StateManager.read_state()` → check idempotency with `stage_run_id`
5. Circuit breaker check (review_cycles >= max)
6. `git.setup_branch(work.format_branch(key), base_branch)`
7. If spec stage and no pr_number in state: `PRLifecycle.create_draft()`
8. `CommentManager.start()`
9. If merge stage: deterministic merge via `PRLifecycle` (check human gate if configured), `CommentManager.finalize()`, return
10. Assemble system prompt (existing `assemble_system_prompt` + auto_spec prefix + skill scoping)
11. Build user_prompt: ticket body for spec/implement, PR context (via `PRLifecycle.read_context()`) for review
12. `StageExecutor.run()` → ExecutionResult
13. `CommentManager.update()` wired as progress callback (via lambda/closure)
14. On failure: `CommentManager.finalize(error_comment)`, set blocked, return
15. On success: format final comment with stats, `CommentManager.finalize(final_comment)`
16. If review stage: `PRLifecycle.post_review()`
17. If implement complete: `PRLifecycle.update_from_result()`
18. Write TicketState via StateManager
19. Commit + push artifacts
20. Determine next stage via `next_stage(stage, status, gates)` — apply gate logic
21. If human gate blocks: post "waiting for approval" comment
22. If auto: `work.set_stage_label()` for next stage
23. Return DispatchResult

**Tests to write (all use fakes_v2):**

*Happy path:*
- Spec complete → one comment created, one finalized, draft PR created, label set to implement
- Implement complete → PR title/body updated from result, label set to review
- Review approved + merge=AUTO → PR merged
- Review approved + merge=HUMAN → no merge, "waiting" comment posted

*Comment lifecycle:*
- Exactly one comment per stage run (assert `len(work.created_comments) == 1`)
- Follow-up retry reuses same comment (no new `begin_comment`)

*Error handling:*
- Runner failure → error comment finalized, blocked
- SkipEvent → early return

*State:*
- TicketState written after each run
- Idempotency: duplicate run_id → skip (runner not called)

*Stats:*
- Cumulative stats across follow-up retries in final comment

*Gates:*
- merge=human default → review approved does NOT trigger merge
- merge=auto override → review approved triggers merge

*Ticket directives:*
- `[a2sdlc base=dev]` → branch created from "dev" base
- Directive stripped from agent's ticket context

*Q&A flow:*
- Questions status → comment finalized, blocked/needs-input set
- Resume event → new comment created (not reusing old)

*Review loop:*
- changes_requested → review_cycles incremented in state

- [ ] Write happy path tests (RED)
- [ ] Implement dispatch skeleton composing the modules
- [ ] Run tests — verify PASS (GREEN)
- [ ] Write error handling tests (RED), implement, verify PASS
- [ ] Write comment lifecycle tests (RED), implement, verify PASS
- [ ] Write gate tests (RED), implement, verify PASS
- [ ] Write Q&A + review loop tests (RED), implement, verify PASS
- [ ] Write stats + idempotency + directive tests (RED), implement, verify PASS
- [ ] Run full suite
- [ ] Commit

---

## Phase 4: Cleanup (Task 16)

---

### Task 16: Clean Up — Update CLI, Fix format_final, Remove v1 Artifacts

**Goal:** Wire everything together, fix remaining bug (#5 tasks not in final), remove deprecated code.

**Files:** Multiple

**Requirements:**

**format_final update (Bug #5):**
- Update `format_final()` in `progress.py` to include task summary in the collapsed `<details>` block
- Tasks with status "completed" show ✅, "in_progress" show 🔄, "pending" show ⬜
- Add test verifying task summary appears in final comment output

**CLI update:**
- Update `cli.py` to construct `DispatchContext` with `work`, `git`, `review`, `runner` fields
- Instantiate `GitHubWorkAdapter` + `GitHubReviewAdapter` (or split existing `GitHubTicketAdapter`)
- Update argument parsing if needed

**v1 cleanup:**
- Remove `BranchState` alias (replace all remaining usages with `TicketState`)
- Remove `PipelineFlags`, `resolve_flags`, `_LABEL_FLAG_MAP` from config.py
- Remove `DispatchInput` from protocols.py
- Remove old `TicketAdapter` protocol
- Remove `load_project` backward-compat shim
- Remove `Gate` enum from models.py
- Update `tests/fakes.py` — either delete or redirect imports to `fakes_v2.py`
- Update all old test files that import v1 types

**Final verification:**
- [ ] Run `make check` (lint + test + coverage + security)
- [ ] All tests pass
- [ ] No v1 artifacts remain
- [ ] Commit

---

## Execution Summary

| Phase | Tasks | Description | Independently Testable |
|-------|-------|-------------|----------------------|
| 1 | 1-7 | Foundation modules | Yes — each task is self-contained |
| 2 | 8-10 | Config & transitions update | Yes — updates existing, tested modules |
| 3 | 11-15 | Dispatch decomposition | Tasks 11-14 independent, Task 15 composes them |
| 4 | 16 | Cleanup | Integration |

| Bug | Fixed In |
|-----|---------|
| #1 Orphaned comment | Task 11 (CommentManager prevents orphans by contract) |
| #2 Brainstorming in implement | Task 10 (skill scoping in prompt) |
| #3 Brainstorming in review | Task 10 (skill scoping in prompt) |
| #4 Stats lost across retries | Task 13 (StageExecutor accumulates via StageRunStats) |
| #5 Tasks not in final comment | Task 16 (format_final update) |
