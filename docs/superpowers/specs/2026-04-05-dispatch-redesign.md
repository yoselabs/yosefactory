# a2sdlc Dispatch Redesign

Date: 2026-04-05

## Problem

The current pipeline splits routing logic between 70 lines of bash in the CI workflow and Python in the engine. This causes:

- Broken transition chains (review→implement→??? — review never re-triggers)
- String-based routing prone to typos and drift
- Two sources of truth for label names (YAML + Python)
- No circuit breaker for review loops
- Untestable bash routing logic
- No structured logging — failures require re-running to diagnose

## Solution

Replace the current architecture with a single `a2sdlc dispatch` entry point. The engine runs **one stage per invocation** and sets a label to trigger the next CI job. Each stage is a separate CI job — visible, re-runnable, composable. Labels are the trigger mechanism, the status dashboard, and the audit trail — all from one source of truth in the adapter.

## Architecture

### Execution model: label chain

Dispatch runs one stage, exits. The label it sets triggers a new CI job for the next stage. No in-process loop.

```
CI Job 1: agent label → dispatch → runs spec → sets stage:implement → exit
CI Job 2: stage:implement label → dispatch → runs implement → sets stage:review → exit
CI Job 3: stage:review label → dispatch → runs review → sets stage:merge → exit
CI Job 4: stage:merge label → dispatch → squash merges → sets stage:done → exit
```

Gates: if a gate is closed (e.g., `auto_proceed=false`), dispatch does NOT set the next label. The pipeline stops until a human sets `proceed` or another trigger label.

### Entry point

```
a2sdlc dispatch [--project-root PATH]
```

No other subcommands. Dispatch does everything: parse event, setup branch, run stage, announce result, trigger next stage. The old `run`, `merge`, `cleanup` subcommands are removed.

For local development/testing: `a2sdlc dispatch --stage spec --key 15` bypasses event parsing and runs directly. Flags can be overridden via `--flag auto_spec --flag auto_merge`.

### Config: a2sdlc.yaml

Lives at project root (not hidden in `.a2sdlc/`). Runtime artifacts (state.json, logs, sessions) stay in `.a2sdlc/`.

```yaml
adapter: github
pipeline:
  auto_spec: false
  auto_proceed: true
  auto_merge: false
  default_base: main
testing:
  command: make test
stages:
  spec:
    code_reviews: 1          # number of /requesting-code-review calls during spec
    max_turns: 35
    timeout_minutes: 30
  implement:
    code_reviews: 2          # number of /requesting-code-review calls during implement
    max_turns: 120
    timeout_minutes: 60
    max_review_cycles: 2     # circuit breaker: max review→implement loops
  review:
    max_turns: 25
    timeout_minutes: 20
jira:                         # only needed when adapter: jira
  status_map:
    "To Do": spec
    "Spec Complete": implement
    "In Review": review
```

No backward compatibility with `.a2sdlc/project.yaml`. Clean break.

### CI workflow (entire file)

```yaml
name: a2sdlc
on:
  issues:
    types: [labeled]
  issue_comment:
    types: [created]
  pull_request:
    types: [labeled]

concurrency:
  group: a2sdlc-${{ github.event.issue.number || github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  agent:
    if: github.event.sender.type != 'Bot'
    runs-on: ubuntu-latest
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - run: pip install git+https://...@github.com/agentic-eng/a2sdlc.git
      - run: a2sdlc dispatch
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

Zero label names in YAML. The engine reads `$GITHUB_EVENT_PATH` and decides.

### State machine

Typed enums — no strings in the hot path.

```python
class StageName(StrEnum):
    SPEC = "spec"
    IMPLEMENT = "implement"
    REVIEW = "review"
    MERGE = "merge"

class StageStatus(StrEnum):
    COMPLETE = "complete"
    QUESTIONS = "questions"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"

class Gate(StrEnum):
    AUTO_PROCEED = "auto_proceed"
    AUTO_MERGE = "auto_merge"

@dataclass(frozen=True)
class Transition:
    next: StageName | None
    gate: Gate | None = None
    # No label/jira_status fields — adapter owns platform mapping

@dataclass
class StageConfig:
    name: str
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_minutes: int = 60
    allowed_tools: list[str] = field(default_factory=list)
    code_reviews: int = 0              # 0-5, injected into stage prompt
    max_review_cycles: int = 2         # circuit breaker (review stage only)
```

The old `StageAction` dataclass and stage `resolve()` methods are removed. Dispatch handles result processing directly: `extract_result()` parses the status, `next_stage()` determines the transition, and adapter methods execute side effects. The `needs-fix` label is also removed — the transition table handles review→implement directly via label chain.

Transition table declared on each stage class:

| State | Status | Gate | Next | On blocked |
|-------|--------|------|------|------------|
| spec | complete | auto_proceed | implement | WAIT for proceed label |
| spec | questions | — | WAIT | needs-input label |
| implement | complete | — | review | always |
| implement | questions | — | WAIT | needs-input label |
| review | approved | auto_merge | merge | WAIT for human merge |
| review | changes_requested | — | implement | stage:blocked if cycles > max |

Each stage class declares its transitions using `Transition` dataclass. Registry validates at import: every `valid_status` must have a matching transition.

The `next_stage()` pure function resolves `(StageName, StageStatus, PipelineFlags) → StageName | None`.

### Pipeline flags

Three booleans. Project defaults in `a2sdlc.yaml`, per-ticket overrides via labels.

```python
@dataclass(frozen=True)
class PipelineFlags:
    auto_spec: bool = False
    auto_proceed: bool = True
    auto_merge: bool = False
```

Label overrides (defined on adapter, not in transitions):

| Label | Effect |
|-------|--------|
| auto-spec | auto_spec=True |
| auto-merge | auto_merge=True |
| spec-only | auto_proceed=False |

**auto_spec mechanism:** When `auto_spec=True`, dispatch injects a prompt prefix into the spec stage: "Make your best judgment for all ambiguous requirements. Do not ask questions — produce the spec directly." This changes behavior via prompt, not via a gate or transition change.

### Key types

```python
@dataclass(frozen=True)
class DispatchInput:
    """Normalized event from the adapter. Platform-agnostic."""
    key: str                          # issue/ticket number
    stage: StageName                  # which stage to run
    labels: frozenset[str]            # all labels on the ticket
    is_resume: bool = False           # true if Q&A continuation
    pr_number: int | None = None      # for review stage

@dataclass
class DispatchContext:
    """All external dependencies — injected, not constructed."""
    tickets: TicketAdapter
    git: GitAdapter
    runner: StageRunner
    config: ProjectConfig
    project_root: Path
    logger: logging.Logger

@dataclass
class DispatchResult:
    """What happened — for testing and logging."""
    stage: StageName
    status: StageStatus | None        # None if error before stage ran
    next_stage: StageName | None
    blocked: bool
    error: str | None
```

### Adapters

Two protocols:

**TicketAdapter** — platform-specific ticket operations:
- `parse_event() → DispatchInput` (raises `SkipEvent` if not our event)
- `get_ticket(key) → str` — issue body for spec/implement; PR context (title, body, diff summary) for review
- `get_labels(key) → list[str]`
- `post_comment(key, body) → str`
- `update_comment(key, comment_id, body)`
- `set_stage_label(key, stage: StageName)` — removes previous stage:X label, sets new
- `set_done_label(key)` — sets terminal stage:done label
- `set_blocked(key, reason)` — sets stage:blocked label + posts comment
- `post_review(pr, body, event)` — GitHub PR review (APPROVE/REQUEST_CHANGES)
- `get_pr_for_branch(branch) → int | None`
- `merge_pr(pr, method="squash")` — merge via platform API (preserves PR metadata)

Owns `STAGE_LABELS: dict[StageName, str]` and `TRIGGER_LABEL`, `BLOCKED_LABEL`, `DONE_LABEL`, `NEEDS_INPUT_LABEL`, `PROCEED_LABEL` constants. All platform label strings live here.

Implementation: `GitHubTicketAdapter` using PyGithub.

**GitAdapter** — local git operations:
- `setup_branch(key, base) → str` (raises `BlockedError` on conflict)
- `sync_with_base(base) → bool`
- `commit_artifacts(message, paths) → bool`
- `push()`

Note: squash merge is done via `tickets.merge_pr()` (platform API), not local git. This preserves PR metadata and status on GitHub.

Note: PR creation is done by the implement stage's Claude agent via its tools (gh CLI), not by the engine. The engine discovers the PR afterward via `tickets.get_pr_for_branch()`.

Implementation: using gitpython.

**StageRunner** — AI stage execution:

```python
class StageRunner(Protocol):
    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        is_resume: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> RunResult: ...
```

Production: `SdkRunner` wraps `claude-agent-sdk`. Tests: `FakeRunner` returns canned `RunResult`.

### Event parsing: what triggers what

The adapter's `parse_event()` handles all event types:

| GitHub Event | Label/Condition | DispatchInput |
|-------------|-----------------|---------------|
| issues.labeled: `agent` | — | stage=SPEC, is_resume=False |
| issues.labeled: `stage:X` | — | stage=X, is_resume=False |
| issues.labeled: `proceed` | reads state.json from branch | stage=IMPLEMENT (or SPEC if state incomplete) |
| issue_comment.created | issue has `needs-input` label, commenter is not bot | stage from state.json, is_resume=True |
| pull_request.labeled: `stage:review` | — | stage=REVIEW, pr_number from event |

Any other event/label → raises `SkipEvent` with reason.

The `proceed` label is special: adapter reads `BranchState` from the agent branch to determine which stage to resume. If state says `spec/complete`, dispatch runs implement. Otherwise it resumes spec.

### Error handling

Two exception types:

- `SkipEvent(reason)` — not our event, exit 0 with log
- `BlockedError(reason)` — unrecoverable, set `stage:blocked` label + comment

Every error path: log full context, post comment so human knows, set blocked label. No silent failures.

| Error | Exception | Recovery |
|-------|-----------|----------|
| Event not ours | SkipEvent | Exit 0, log reason |
| Git conflict | BlockedError | stage:blocked + comment |
| Stage failure (SDK error, timeout) | BlockedError | stage:blocked + error comment with cost footer |
| No status block in output | BlockedError | stage:blocked + partial output (first 2000 chars) for debugging |
| Review cycles > max | BlockedError | stage:blocked + circuit breaker message |

### Circuit breaker

Review cycle count tracked in `BranchState`:

```python
class BranchState(BaseModel):
    stage: StageName
    status: StageStatus
    base_branch: str = "main"      # default handles legacy state files
    review_cycles: int = 0
    last_updated: str
```

On `changes_requested`: increment `review_cycles`. If `> max_review_cycles` (from stage config): raise `BlockedError` instead of looping back to implement.

### Dispatch flow

1. Load `a2sdlc.yaml`, construct adapters
2. `tickets.parse_event()` → `DispatchInput` (or `SkipEvent`)
3. Resolve `PipelineFlags` from project defaults + label overrides
4. Read `BranchState` from agent branch (if exists)
5. Check circuit breaker: if review stage and `review_cycles > max` → `BlockedError`
6. `git.setup_branch(key, base)` (or `BlockedError` on conflict)
7. Post "started" comment, set `stage:X` label via `tickets.set_stage_label()`
8. If merge stage: `tickets.merge_pr()` + `tickets.set_done_label()`, done
9. If `auto_spec` and stage is spec: prepend auto-spec prompt prefix
10. Run AI stage via `runner.run()`, with progress callback updating the comment
11. Parse result: `extract_result()` → `StageResult`, `strip_status_block()` → comment body, `format_cost()` → footer
12. Update comment with result + cost footer
13. Execute side effects: `tickets.post_review()` if review stage, write `BranchState`
14. `git.commit_artifacts()` + `git.push()`
15. Check transition via `next_stage()`:
    - Next stage exists and gate open → `tickets.set_stage_label(next)` (triggers next CI job)
    - Next stage exists and gate closed → stop (human triggers via `proceed` or manual merge)
    - No next stage (questions/wait) → stop
16. Return `DispatchResult`

### Observability (LDD)

Structured JSON logging at every decision point:

```python
logger.info("dispatch.start", extra={
    "key": "15", "stage": "spec", "flags": {...}, "base_branch": "main"
})
logger.info("dispatch.branch_setup", extra={
    "branch": "agent/15", "base": "main", "created": True
})
logger.info("dispatch.stage_complete", extra={
    "stage": "spec", "status": "complete",
    "duration_ms": 45000, "cost_usd": 0.12,
    "tokens_in": 5000, "tokens_out": 2000, "tool_count": 15,
})
logger.info("dispatch.transition", extra={
    "from": "spec", "to": "implement",
    "gate": "auto_proceed", "gate_open": True,
})
logger.info("dispatch.done", extra={
    "key": "15", "stage": "spec", "next": "implement", "blocked": False
})
```

GitHub Actions `::group::` annotations wrap each phase for CI-level visibility.

Logs must be sufficient to reconstruct the full run without re-executing.

### Transparency

Each stage produces visible artifacts:
- **Label:** `stage:X` on the issue (one at a time, previous removed). Terminal: `stage:done`.
- **Comment:** per-stage start + result comment with cost footer
- **Jira status:** adapter maps `StageName` → Jira status (if configured)

At any point, looking at the issue: label shows current stage, comments show full history.

### Branch strategy

CI checks out main. Engine creates/switches to `agent/{key}` branch at runtime.

Base branch: parsed from ticket body (`base: feature/new-api`) or `default_base` from config.

Before merge: sync agent branch with base via `git.sync_with_base()`. On conflict: `stage:blocked`.

Merge itself done via `tickets.merge_pr()` (GitHub API squash merge), not local git. This preserves PR metadata.

## Dependencies

New:
- `PyGithub` — GitHub ticket adapter
- `gitpython` — git adapter

Existing:
- `claude-agent-sdk` — AI stage runner
- `pydantic` — structured output parsing
- `pyyaml` — config loading
- `rich` — console output

## Files changed

### New
- `src/a2sdlc/dispatch.py` — dispatch function + DispatchContext/Result
- `src/a2sdlc/exceptions.py` — SkipEvent, BlockedError
- `src/a2sdlc/adapters/github_tickets.py` — GitHubTicketAdapter (PyGithub)
- `src/a2sdlc/adapters/git.py` — GitAdapter (gitpython)
- `src/a2sdlc/adapters/protocols.py` — TicketAdapter, GitAdapter, StageRunner protocols
- `tests/test_dispatch.py` — dispatch integration tests
- `tests/test_github_adapter.py` — GitHub adapter unit tests
- `tests/test_git_adapter.py` — git adapter unit tests
- `tests/fakes.py` — FakeTicketAdapter, FakeGitAdapter, FakeRunner

### Modified
- `src/a2sdlc/models.py` — BranchState updated (base_branch, review_cycles), Transition drops label/jira_status fields
- `src/a2sdlc/config.py` — load from a2sdlc.yaml, StageConfig + code_reviews/max_review_cycles, PipelineFlags
- `src/a2sdlc/cli.py` — gutted, dispatch-only entry point
- `src/a2sdlc/stages/*.py` — stage configs read from a2sdlc.yaml overrides

### Removed
- `src/a2sdlc/verifier.py` — logic absorbed into dispatch (extract_result, strip_status_block, format_cost move to models/runner)
- `src/a2sdlc/adapters/github_issues.py` — replaced by github_tickets.py
- `src/a2sdlc/adapters/github_code.py` — merged into github_tickets.py
- Old tests for removed modules

## Use cases validated

| UC | Flags | Flow |
|----|-------|------|
| UC1 Full auto | auto_spec, auto_proceed, auto_merge | agent → spec(auto) → stage:implement → implement → stage:review → review → stage:merge → merge → stage:done |
| UC2 Interactive + auto | auto_proceed, auto_merge | agent → spec(Q&A) → needs-input → human answers → spec resumes → stage:implement → ... → stage:done |
| UC3 Interactive + manual merge | auto_proceed | agent → spec(Q&A) → stage:implement → implement → stage:review → review → WAIT → human merges |
| UC4 Spec only | spec-only label | agent → spec(Q&A) → WAIT → human adds proceed → stage:implement → ... |
| UC5 Auto spec + manual merge | auto-spec label | agent → spec(auto) → stage:implement → ... → review → WAIT |

## Testing strategy (TDD)

All implementation follows red-green-refactor.

**Layer 1: Unit tests** — pure functions, no mocks needed:
- Transition table completeness (already done — 26 tests)
- `next_stage()` with all flag combinations (already done)
- Flag resolution from labels
- Circuit breaker logic

**Layer 2: Adapter tests** — mock PyGithub/gitpython:
- `parse_event()` for each event type + SkipEvent cases
- `parse_event()` for Q&A resume (issue_comment + needs-input)
- `parse_event()` for proceed label (reads BranchState)
- `set_stage_label()` removes old, sets new
- `set_done_label()` sets terminal label
- `git.setup_branch()` create vs checkout vs conflict
- `git.commit_artifacts()` with allowlist

**Layer 3: Dispatch integration** — fake adapters, real dispatch logic:
- Full UC1-UC5 flows
- Error paths (conflict, SDK failure, no status block)
- Circuit breaker triggering
- SkipEvent for non-a2sdlc labels
- Q&A resume round-trip
- auto_spec prompt injection

## Not in scope

- Deploy stage (post-merge)
- Staleness revalidation
- Review-to-spec loop (review → spec, not just implement)
- Multiple reviewers
- Cost budgets
- Ticket batching
- GitLab/Jenkins adapters (architecture supports them, not building now)
