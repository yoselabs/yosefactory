# Engine Architecture v2

Redesign of the a2sdlc engine prompted by production bugs found in iorlas/a2db-demo2#35 and the need to support multiple ticket/code platforms.

## Context

### Bugs That Prompted This

1. **Orphaned in-progress comment** -- auto-approve retry called `post_comment()` instead of reusing `comment_id`, leaving a stale progress comment on the ticket.
2. **Brainstorming invoked in implement stage** -- Superpowers `using-superpowers` skill overrides stage prompt, forces brainstorming everywhere.
3. **Brainstorming invoked in review stage** -- same root cause as #2.
4. **Stats lost across retries** -- `RunResult` only captures last run's tokens/cost; auto-approve retry discards first run's metrics.
5. **Tasks not shown in final comment** -- `format_final()` omits task status.

### Platforms to Support

| Role | Platforms |
|------|-----------|
| Issue tracker | Jira Cloud/DC, GitHub Issues, GitLab Issues, ADO Work Items, Linear |
| Code host | GitHub, GitLab, ADO Repos, Forgejo/Gitea |

Key constraints discovered during research:

| Platform | Max comment | Rate limit | Edit support | Format |
|----------|------------|------------|-------------|--------|
| Jira | 32K chars | 20 writes/2s per issue | Yes | ADF (v3) / wiki (v2) |
| GitHub | ~65K chars | 180 edits/min | Yes (not submitted reviews) | Markdown |
| GitLab | 1MB | 2K req/min | Yes | Markdown |
| ADO | 1M chars | Abstract TSTUs | Yes | MD/HTML |
| Linear | Unknown (test empirically) | 1500 req/hr | Yes | Markdown |
| Forgejo | No limit | None (proxy-level) | Yes | Markdown |

All platforms support comment editing. Jira is the constraint bottleneck (32K body, ADF format, strict rate limits).

## Adapter Architecture

Three adapters split by concern. In enterprise setups, tickets and code reviews live on different platforms (Jira + GitHub). Git operations have different auth and failure modes from platform APIs.

### WorkAdapter

Handles ticket/issue operations. One implementation per issue tracker.

```
WorkAdapter (protocol)
  get_ticket(key) -> body
  get_labels(key) -> list[str]
  set_stage_label(key, stage)
  set_done_label(key)
  set_blocked(key, reason)
  parse_event() -> PipelineEvent

  begin_comment(key) -> comment_id
  update_progress(comment_id, body)   # may debounce
  finalize_comment(comment_id, body)  # must flush

  format_branch(ticket_key) -> str
```

Implementations: GitHub, Jira, GitLab, ADO, Linear, Forgejo.

### GitAdapter

Pure local git operations. Same implementation everywhere.

```
GitAdapter (protocol)
  setup_branch(branch_name, base_branch)
  sync_with_base(base_branch)
  commit_artifacts(message, paths)
  push()
  read_state() -> str | None
  write_state(json_str)
```

Implementation: LocalGitAdapter (gitpython).

### ReviewAdapter

Handles PR/MR lifecycle and code review. One implementation per code host.

```
ReviewAdapter (protocol)
  create_draft_pr(branch, base, title, ticket_key) -> pr_number
  update_pr(pr_number, title, body, ticket_key)
  mark_pr_ready(pr_number)
  merge_pr(pr_number, method)
  get_approvals(pr_number) -> list[Approval]

  post_review(pr_number, body, verdict)
  read_pr_diff(pr_number) -> str
  read_pr_comments(pr_number) -> list[Comment]
```

`update_pr` receives `ticket_key` from the engine and internally appends platform-specific auto-linking footer (e.g., "Closes #35" for GitHub). The engine passes clean content and the ticket key; the adapter adds platform concerns. No adapter-to-adapter communication — the engine mediates.

`read_pr_diff` and `read_pr_comments` are called by the engine to build user_prompt for the review stage. The agent never calls platform APIs directly -- this makes all stages platform-agnostic.

Implementations: GitHub, GitLab, ADO, Forgejo.

## Comment Lifecycle

Engine-owned. Adapters implement CRUD with platform-specific behavior (debouncing, rate limiting, body truncation).

### Contract

```
begin_comment(key) -> comment_id
update_progress(comment_id, body)   # best-effort, adapter may debounce
finalize_comment(comment_id, body)  # must-succeed, engine retries with tenacity
```

Rules:
- One comment per stage run. No exceptions.
- Auto-approve retries reuse the same comment_id.
- Each new stage run (including Q&A resume) gets a new comment via `begin_comment`.
- `comment_id` is stored in `TicketState`.

### Adapter Responsibilities

- **Debouncing:** Jira adapter may limit `update_progress` to once per 5 seconds. GitHub adapter fires immediately.
- **Body truncation:** If body exceeds platform limit, adapter truncates with "... [full output in PR]" suffix. Safety net -- the agent is also prompted to keep summaries concise.
- **Format translation:** Jira adapter converts markdown to ADF. Others pass through.

### Progress Comment Content

During execution, the comment shows:

- Status bar: model, branch, context window %, cost, duration, turns
- Skill checkpoints with timestamps
- Task list with status icons
- Sub-agent status (if any)
- Last 10 tool calls with timestamps

### Finalized Comment Content

On completion:

- Stage header with status icon
- Ticket summary from agent (with links)
- Collapsed `<details>` block: status bar, skill checkpoints, cumulative stats

On error:

- Error description
- Collapsed `<details>` block: stats from the failed run

## Two-Layer Content Strategy

Ticket comments are summaries with links. Heavy output goes to PR.

| Content | Where |
|---------|-------|
| Stage status + summary | Ticket comment (WorkAdapter) |
| Links to spec/plan files | Ticket comment |
| Full agent implementation output | PR description (ReviewAdapter) |
| Code review feedback (inline) | PR review comments (ReviewAdapter) |
| Stats, milestones | Ticket comment (collapsed) |

## Follow-Up Prompt Pattern

Instead of embedding structured output requirements in the system prompt (fragile, often ignored), the engine sends a follow-up message after the agent completes its work.

### Flow

1. Engine sends `system_prompt` (role, skills, stage constraints) + `user_prompt` (ticket context, PR context for review).
2. Agent works freely.
3. Agent signals completion or hits max turns.
4. Engine sends follow-up prompt with concrete context:

```
Work phase complete. Produce your handover:

Repository: {repo_url}
Branch: {branch}
File links use: {repo_url}/blob/{branch}/path
Max summary length: 2000 chars

Respond with ONLY the structured block:

    ```a2sdlc
    {
      "status": "complete|questions|approved|changes_requested",
      "pr_title": "...",
      "pr_summary": "...",
      "ticket_summary": "...",
      "spec_path": "...",
      "plan_path": "...",
      "questions": ["..."]
    }
    ```
```

Note: for `status: "questions"`, the agent's main output (before the follow-up) contains the detailed question context. The follow-up captures the structured status and a summary of questions. The engine uses both: main output for the ticket comment body, structured block for routing.

### Per-Stage Follow-Up

| Stage | Fields requested |
|-------|-----------------|
| Spec | status, ticket_summary (with full links to spec and plan files) |
| Implement | status, pr_title, pr_summary, ticket_summary (with PR link) |
| Review | status (approved/changes_requested), ticket_summary (verdict summary) |

### Mechanism

The follow-up is a session resume. After the runner returns a `ResultMessage`, the engine checks for a valid status block. If absent, engine calls `runner.run()` again with:
- `user_prompt` = the follow-up template (with interpolated values)
- `is_resume = True` (continues the same Claude Code session)
- Same `session_id` as the work phase

This is the same mechanism as auto-approve retry, but with a targeted prompt instead of a generic "proceed." The cost is one additional turn in the existing session — context is already loaded, so there is no cache miss.

If the follow-up response also lacks a valid status block, retry up to 2 more times with increasingly explicit instructions. After 3 failed attempts, engine extracts what it can from the agent's main output and posts a partial result with a warning.

### Benefits

- System prompt stays focused on the work.
- Agent has concrete context for links (repo_url, branch) at output time.
- If agent doesn't produce valid output, retry the follow-up only (cheap — one turn, not a full re-run).
- Adapter body size limit can be passed in the follow-up template.

## Pipeline Flow

```
  [SPEC] ---> [IMPLEMENT] ---> [REVIEW] ---> [MERGE]
                   ^               |
                   |  changes_requested
                   +---------------+
```

### Stage Transitions

| From | Status | To | Gate |
|------|--------|----|------|
| Spec | complete | Implement | -- (always auto) |
| Spec | questions | (wait for human) | -- |
| Implement | complete | Review | review gate |
| Implement | questions | (wait for human) | -- |
| Review | approved | Merge | merge gate |
| Review | changes_requested | Implement | -- (always auto) |

### Gate System

```python
class GateMode(str, Enum):
    AUTO = "auto"
    HUMAN = "human"

class GateConfig(BaseModel):
    merge: GateMode = GateMode.HUMAN
    review: GateMode = GateMode.AUTO
```

Configured in `a2sdlc.yaml` (project default). Per-ticket override via ticket directives.

**Migration from v1 PipelineFlags:**

| v1 flag | v2 equivalent | Notes |
|---------|--------------|-------|
| `auto_spec` | Preserved as `auto_spec: bool` in config | Not a gate — it's a prompt modifier ("don't ask questions"). Injected into system prompt when true. |
| `auto_proceed` | Dropped | v1 gated spec → implement. In v2, spec → implement is always auto (no gate). The `spec-only` use case is covered by `gate:review=human` (stops after implement, before review). |
| `auto_merge` | `gates.merge: auto` | Review → merge transition. AUTO = merge immediately. HUMAN = wait for PR approval. |

Label-based overrides are replaced by ticket directives (`[a2sdlc ...]` syntax).

| Gate | AUTO behavior | HUMAN behavior |
|------|--------------|----------------|
| merge | Engine marks PR ready + merges immediately | Engine marks PR ready, posts "approve PR to proceed", waits for human PR approval |
| review | Review stage runs automatically after implement | Engine posts "implementation done", waits for human to trigger review |

### Draft PR Lifecycle

The PR exists from spec start as a container for all work:

1. **Spec starts** -- engine creates branch, commits initial TicketState, pushes, then creates draft PR (placeholder title). The initial commit ensures the branch exists on the remote before PR creation.
2. **Spec completes** -- engine updates PR body with spec/plan links.
3. **Implement** -- agent commits code to branch.
4. **Implement completes** -- engine updates PR title + description from follow-up output.
5. **Review** -- ReviewAdapter posts review on PR.
6. **Merge (auto gate)** -- engine marks PR ready + merges.
7. **Merge (human gate)** -- engine marks PR ready, waits for human approval, then merges.

## State Management

### TicketState

Replaces `BranchState`. Single file per ticket, committed after every stage run.


```python
class TicketState(BaseModel):
    stage: StageName
    status: StageStatus | None = None
    base_branch: str = "main"
    branch: str
    pr_number: int | None = None
    stage_run_id: str
    comment_id: str | None = None
    review_cycles: int = 0
    accumulated_cost_usd: float = 0.0
    accumulated_tokens_in: int = 0
    accumulated_tokens_out: int = 0
    accumulated_duration_ms: int = 0
    last_updated: str
```

Stored at `.a2sdlc/tickets/{key}/state.yaml`.

### Stats Accumulation

Engine maintains a `StageRunStats` accumulator during dispatch. After each runner invocation (including auto-approve retries), engine adds the result:

```python
@dataclass
class StageRunStats:
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    num_turns: int = 0

    def add(self, result: RunResult) -> None:
        self.cost_usd += result.total_cost_usd
        self.tokens_in += result.input_tokens
        self.tokens_out += result.output_tokens
        self.duration_ms += result.duration_ms
        self.num_turns += result.num_turns
```

The final comment and TicketState both read from this accumulated object. On a new stage run (including `changes_requested` loop), stats reset — prior runs are preserved in git history.

### Idempotency

Before running a stage, engine checks if `stage_run_id` in TicketState matches the current event. If yes, skip — prevents duplicate runs from re-delivered webhooks.

`stage_run_id` is derived from the CI environment:
- GitHub Actions: `{GITHUB_RUN_ID}-{GITHUB_RUN_ATTEMPT}`
- Other CI: engine generates a UUID, passed via `A2SDLC_RUN_ID` environment variable.

If no run ID is available (local dev), engine generates a random UUID per invocation. The key property: same webhook delivery producing the same CI job produces the same `stage_run_id`.

### Session Persistence

Claude Code session files stored per ticket at `.a2sdlc/tickets/{key}/`. On merge, the entire ticket subfolder is deleted after successful merge confirmation.

Session reuse is controlled by session ID generation:

```python
def get_session_id(key: str, stage: str, review_cycles: int = 0) -> str:
    """Deterministic session ID. Include review_cycles to force
    fresh sessions on changes_requested loops."""
    return str(uuid5(NAMESPACE, f"a2sdlc:{key}:{stage}:{review_cycles}"))
```

Session reuse rules:
- **Q&A resume:** reuse session (human is continuing the same conversation).
- **Auto-approve retry:** reuse session (same work, just needs structured output).
- **changes_requested loop:** new session (fresh context, reads review feedback from PR).
- **Error retry:** reuse session if possible (human retries via CI).

## Ticket Directives

Engine-level parsing of `[a2sdlc key=value]` lines in ticket description. Stripped before passing ticket body to agent.

```
[a2sdlc base=feature/approach-a gate:merge=human model=opus]

Implement patient information form. API only, no visuals.
```

```python
class TicketDirectives(BaseModel):
    base: str | None = None
    gate_merge: GateMode | None = None
    gate_review: GateMode | None = None
    model: str | None = None
```

Precedence: `a2sdlc.yaml` defaults < ticket directives.

Parsing is a utility function in the engine, not in adapters. Platform-agnostic -- works on every platform because it's just text.

## Question/Answer Flow

1. Agent returns `{"status": "questions"}` with questions in output.
2. Engine finalizes comment: "Questions -- see below" + questions text.
3. Engine writes TicketState (stage, status=QUESTIONS).
4. WorkAdapter sets needs-input label/state on ticket.
5. Human writes answer as comment on ticket.
6. CI triggers. `parse_event()` detects comment + needs-input state.
7. Engine reads stage from TicketState (not hardcoded).
8. Engine creates new comment (`begin_comment`), new `stage_run_id`.
9. Engine resumes same Claude Code session with human's answer as `user_prompt`.
10. Agent continues with full context. May complete or ask more questions.
11. No circuit breaker on Q&A -- agent/superpowers decides when to stop.

## Skill Scoping

Each stage prompt includes explicit context about completed phases and prohibited skills:

| Stage | Context added to system prompt |
|-------|-------------------------------|
| Spec | "Use brainstorming and writing-plans skills." |
| Implement | "Brainstorming and design are COMPLETED. Do NOT invoke brainstorming. Use: subagent-driven-development, test-driven-development, requesting-code-review, verification-before-completion." |
| Review | "This is an independent code review. Do NOT invoke brainstorming or writing-plans. Review the code on its merits." |

No hard allowed_skills list -- agent can discover useful new skills. Explicit "DO NOT" for known-bad patterns only.

## Branch Naming

WorkAdapter provides `format_branch(ticket_key)`:

| Adapter | Example |
|---------|---------|
| GitHub | `agent/35` |
| Jira | `agent/PROJ-123` |
| GitLab | `agent/123` |
| Linear | `agent/TEAM-123` |
| ADO | `agent/AB123` |

Engine calls `work_adapter.format_branch()` and passes the result to GitAdapter and ReviewAdapter. No adapter-to-adapter communication.

### Auto-Linking

Branch naming follows platform conventions. If the appropriate integration is installed (GitHub for Jira app, Linear GitHub integration, etc.), auto-linking happens automatically. If not, ticket comments contain PR links anyway. Auto-linking is a nice-to-have, not architecturally critical.

## Base Branch Override

Default base branch is configured in `a2sdlc.yaml`. Per-ticket override via ticket directive:

```
[a2sdlc base=feature/approach-a]
```

Use case: experimenting with different implementation approaches on separate branches.

Precedence: `a2sdlc.yaml:default_base` < `[a2sdlc base=...]` directive.

## Retry & Error Handling

### Exception Taxonomy

```python
class AdapterError(Exception): ...

class RetryableError(AdapterError): ...
class RateLimitError(RetryableError):
    retry_after: float
class TransientError(RetryableError): ...

class PermanentError(AdapterError): ...
class AuthError(PermanentError): ...
class NotFoundError(PermanentError): ...
class PlatformValidationError(PermanentError): ...
```

### Must-Succeed vs Best-Effort

Must-succeed calls get tenacity retry with exponential backoff + structured logging:
- `finalize_comment` -- can't leave comment stuck as in-progress
- `set_stage_label` -- drives the state machine
- `merge_pr` -- final step
- `mark_pr_ready` -- transition before merge

Best-effort calls get single try + log on failure:
- `update_progress` -- next update overwrites anyway

### Retry Policy

```python
@retry(
    retry=retry_if_exception_type(RetryableError),
    wait=wait_exponential(multiplier=1, max=60),
    stop=stop_after_attempt(5),
    before_sleep=log_retry_structured,
)
```

Every retry produces a structured log entry. Retries are not expected behavior and must be visible in telemetry.

**New dependency:** `tenacity` (add to `pyproject.toml`).

## Review Loop

When review returns `changes_requested`:

1. Engine finalizes review comment on ticket with verdict summary.
2. ReviewAdapter posts REQUEST_CHANGES review on PR.
3. Engine writes TicketState (review_cycles += 1).
4. Engine sets stage:implement label.
5. New CI run triggers.
6. Implement starts with FRESH session (no session reuse).
7. User prompt includes: ticket context + "Review feedback is on PR #{pr_number}. Read it and address the issues."
8. Agent reads PR review comments via ReviewAdapter context, reads its own code on branch, makes targeted fixes.
9. Cycle repeats until approved or circuit breaker (`max_review_cycles`).

## Test Strategy

All implementation follows strict red-green-refactor TDD:

1. **Red:** Write a failing test that describes the desired behavior.
2. **Green:** Write the minimum code to make the test pass.
3. **Refactor:** Clean up while keeping tests green.

Every feature, bugfix, and adapter starts with a test. No code without a failing test first.

### TDD Workflow Per Feature

```
For each feature/component:
  1. Write test for the contract (what it should do)
  2. Run test -- verify it FAILS (red)
  3. Implement minimum code to pass
  4. Run test -- verify it PASSES (green)
  5. Refactor if needed, run tests again
  6. Commit: "test: add X" then "feat: implement X"
```

### Layer 1: Contract Tests (unit)

Test the engine's internal contracts in isolation. These are written FIRST, before any implementation.

**Comment lifecycle contract:**
- `begin` -> `update` * N -> `finalize` produces exactly one comment per stage run.
- Auto-approve retry reuses same `comment_id` (no new `begin`).
- New stage run (Q&A resume, new stage) calls `begin` for a new comment.
- `finalize` is always called exactly once per stage run (success or failure).

**Stats accumulation:**
- Cumulative tokens/cost across retries within a stage run.
- Stats reset on new stage run.
- TicketState reflects accumulated values after each run.

**Ticket directives:**
- `[a2sdlc base=X]` parsed from ticket body, stripped before agent sees it.
- Multiple directives parsed correctly.
- Malformed directives ignored (not crash).
- Precedence: config defaults < ticket directives.

**Idempotency:**
- Duplicate `stage_run_id` -> skip, no side effects.
- Different `stage_run_id` -> proceed.

**TicketState:**
- Serialization roundtrip (YAML).
- All fields populated after stage run.
- `comment_id` tracked correctly across lifecycle.

**Follow-up prompt:**
- Follow-up sent after agent completes (not during).
- Correct template selected per stage.
- `repo_url`, `branch`, `pr_number` interpolated.
- Missing status block in follow-up response triggers retry.

**Exception taxonomy:**
- `RetryableError` subclasses are retried.
- `PermanentError` subclasses are not retried.
- `RateLimitError.retry_after` is respected by wait strategy.

**Gate logic:**
- `GateMode.AUTO` -> immediate transition.
- `GateMode.HUMAN` -> no transition, posts "waiting for approval" comment.
- Ticket directive overrides project config.

**Branch naming:**
- Each adapter returns correct pattern for its platform.
- Fake adapter matches real adapter pattern (no divergence).

### Layer 2: Integration Tests (with fakes)

Test the dispatch flow end-to-end using fake adapters. Written after Layer 1, exercising the full pipeline.

**Happy path:**
- Full dispatch cycle: spec -> implement -> review -> merge.
- Each stage produces exactly one comment (begin + updates + finalize).
- TicketState transitions correctly at each step.
- Draft PR created at spec start, updated at implement completion.
- PR merged at merge stage.

**Question flow:**
- Agent returns questions -> comment finalized -> needs-input set.
- Human comment triggers resume -> new comment created.
- Correct stage resumed from TicketState (not hardcoded).
- Multiple Q&A rounds work correctly.

**Review loop:**
- `changes_requested` -> implement reruns with fresh session.
- `review_cycles` incremented.
- Circuit breaker triggers at `max_review_cycles`.
- Review feedback passed via PR context (not session memory).

**Error handling:**
- Runner failure -> error comment finalized -> blocked.
- Retry succeeds -> cumulative stats in final comment.
- Auto-approve retry reuses same comment (no orphan).

**Gates:**
- `gate:merge=human` -> pipeline stops after review, resumes on PR approval.
- `gate:review=human` -> pipeline stops after implement, resumes on trigger.
- Auto gates -> pipeline runs end-to-end without stopping.

**Follow-up prompt:**
- Engine sends follow-up after agent work completes.
- Structured output parsed correctly from follow-up response.
- PR title/description updated from follow-up output.
- Ticket comment contains summary from follow-up output.

**Base branch override:**
- Ticket directive `[a2sdlc base=X]` -> branch created from X.
- Default base used when no directive present.
- Directive stripped from agent's ticket context.

**Adapter retry integration:**
- `finalize_comment` retried on `RetryableError`, succeeds after N attempts.
- `set_stage_label` retried on `RateLimitError`, respects `retry_after`.
- `update_progress` failure logged but not retried, pipeline continues.
- All retries produce structured log entries.

### Layer 3: Adapter Tests (per platform)

Test each adapter implementation against its platform's constraints. Written when implementing each adapter.

**Common adapter contract (all platforms):**
- `begin_comment` creates a comment, returns ID.
- `update_progress` with same ID updates (not creates) the comment.
- `finalize_comment` with same ID updates the comment.
- `format_branch` returns platform-correct pattern.

**Debouncing (Jira, rate-limited platforms):**
- 10 rapid `update_progress` calls -> at most N actual API calls.
- Last update is always the one that persists.
- `finalize_comment` always flushes, even if debounce window hasn't elapsed.

**Rate limit handling:**
- Mock 429 response -> raises `RateLimitError` with correct `retry_after`.
- Mock 502/503 -> raises `TransientError`.
- Mock 401 -> raises `AuthError`.

**Body truncation:**
- Body exceeding platform limit -> truncated with "... [full output in PR]".
- Truncation preserves the status bar (never truncated).
- Body exactly at limit -> no truncation.

**Format translation (Jira):**
- Markdown status bar -> ADF equivalent.
- `<details>` blocks -> ADF expand nodes.
- Tables -> ADF table nodes.

**Auto-linking footer (ReviewAdapter):**
- `update_pr` on GitHub appends "Closes #{key}" to body.
- `update_pr` on GitLab appends "Closes #{key}".
- Footer not duplicated on repeated `update_pr` calls.

**Draft PR lifecycle (ReviewAdapter):**
- `create_draft_pr` creates PR in draft state.
- `mark_pr_ready` transitions to ready/open state.
- `get_approvals` returns list with `is_bot` flag per approver.

### Layer 4: Agent Behavior Tests (non-deterministic)

Test that stage prompts produce correct agent behavior. Run against real Claude. Slow, golden-path only.

**Skill scoping:**
- Implement prompt -> agent does NOT invoke brainstorming.
- Review prompt -> agent does NOT invoke brainstorming or writing-plans.
- Spec prompt -> agent DOES invoke brainstorming.

**Follow-up compliance:**
- Agent produces valid `a2sdlc` status block from follow-up prompt.
- Status block contains all required fields for the stage.
- Links in ticket_summary are absolute URLs (not relative paths).

**Review feedback:**
- When user_prompt includes "review feedback is on PR", agent reads PR context.
- Agent makes targeted fixes based on review comments.

**These tests are:**
- Run separately from the main test suite (not in `make test`).
- Triggered manually or on a schedule.
- Allowed to be flaky — assertions are soft (pattern matching, not exact equality).
- Expensive — each test is a real Claude API call.

### Coverage Requirements

- **Layer 1-2:** 95% diff-coverage enforced via `diff-cover` (existing gate).
- **Layer 3:** 90% coverage per adapter implementation.
- **Layer 4:** No coverage gate — these validate behavior, not code paths.

All tests run in CI via `make check`. Layer 4 runs via `make test-agent` (separate, manual).

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Comment body exceeds platform limit | Adapter truncates with "[full output in PR]" suffix + agent prompted with max size |
| Finalize fails (rate limited) | Tenacity retry, engine blocks until confirmed |
| Session file not cleaned before merge | Merge stage deletes ticket subfolder after successful merge confirmation |
| Base branch diverges during long implementation | `sync_with_base()` before PR creation (TODO: merge conflict resolution) |
| Human answers question but CI doesn't trigger | `parse_event()` handles all comment events on tickets with needs-input state, logs skips |
| Agent produces relative links | Follow-up prompt provides repo_url + branch for absolute URL construction |
| Duplicate webhook delivery | Idempotency check via stage_run_id in TicketState |
| Bot self-approves on platforms that allow it | `require_human_approval` via gate config, engine checks `get_approvals()` for non-bot approver |

## TODO (parked for future iterations)

- **Clean up a2db-demo2 test repo:** Force push rewritten history (weekend-only commits from Jan 3). Clean up stale agent branches, close/clean issues from v1 testing (e.g., issue #35). Update workflow to use v2 engine once implemented. This is the primary integration test target for v2.
- **Compression flow:** Handle context window exhaustion during long implementations.
- **Epic-level orchestration:** Epic -> brainstorm -> create Stories -> run pipeline per story. Includes concurrency control and priority ordering.
- **Cross-ticket awareness:** Agent detecting related tickets during spec.
- **Concurrent command handling:** Two humans commenting simultaneously on same ticket. Solve with lock file or CI concurrency groups.
- **Merge conflict resolution:** When `sync_with_base` finds conflicts. Agent attempts resolution or blocks for human.
- **Initialization stage:** Lightweight stage for branch/PR setup based on ticket context (may be useful for epic orchestration).
- **Custom platform:** Build own platform with fewer constraints, reuse same engine and process.
