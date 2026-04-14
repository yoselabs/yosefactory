# Feedback-Aware Pipeline with Handover Pattern

Design for the a2sdlc pipeline: feedback handling, handover-based context, stages as independent products.

## Context

### Problem

The pipeline runs SPEC -> IMPLEMENT -> REVIEW -> MERGE with one feedback loop (REVIEW.changes_requested -> IMPLEMENT). Real-world feedback comes from many sources:

- Human engineers: PR inline comments, PR general comments
- Human QA/BA: comments on the issue/ticket
- AI tools (CodeRabbit, Copilot): PR review comments
- Human code reviewers: PR reviews with "changes requested"

The engine cannot collect this feedback, route it to the agent, or distinguish "this is for the AI" from human-to-human conversation.

### Goals

1. Agent receives and acts on feedback from any source
2. Each stage is independently observable (separate CI job, comment, log)
3. Stages can be deployed standalone (e.g., REVIEW as a GitHub Action)
4. Architecture supports GitHub, GitLab, Forgejo, Jira (build for GitHub first)
5. No external server or queue — everything runs inside CI

### Non-Goals (Backlog)

- Inline PR comment threading (agent replies to specific code line threads)
- Semantic noise filtering (NLP-based "is this for the AI?")
- CodeRabbit/Copilot special handling (advisory vs authoritative weighting)
- Custom dashboard or owned UI
- GitLab cron sweep (design supports it, build later)
- Jira adapter implementation (design supports it, build later)

## Architecture

### Core Principles

1. **CI is the execution layer.** No external server, no queue, no webhook receiver.
2. **One stage per CI job.** Each stage has its own log, comment, and timing. Always.
3. **Event-triggered, state-reconciled.** Events wake the engine. The engine reads full current state and decides what to do.
4. **@mention gating.** Comments trigger the engine only if they contain `@a2sdlc`. PR review submissions always trigger. Label events always trigger.
5. **Handover comments as contracts.** Each stage produces a structured comment that becomes the input for the next stage.
6. **Stages are functions.** Same code runs standalone or in the pipeline. The caller decides context and routing.

### Trigger Model

| Event | Filter | Purpose |
|-------|--------|---------|
| `issues.labeled` | None (always) | Stage transitions via labels |
| `issue_comment.created` | `contains(body, '@a2sdlc')` | Feedback on issues |
| `pull_request_review.submitted` | `sender.type != 'Bot'` | Code review submissions |
| `pull_request_review_comment.created` | `contains(body, '@a2sdlc')` | Inline PR feedback |

Label events always fire (including bot-set labels for stage transitions). Comment events require @mention. PR review submissions are always actionable — submitting a review is a deliberate act.

Reference CI workflow:

```yaml
on:
  issues:
    types: [labeled]
  issue_comment:
    types: [created]
  pull_request_review:
    types: [submitted]
  pull_request_review_comment:
    types: [created]

jobs:
  dispatch:
    if: |
      (github.event_name == 'issues') ||
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@a2sdlc')) ||
      (github.event_name == 'pull_request_review' && github.event.sender.type != 'Bot') ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@a2sdlc'))
    concurrency:
      group: a2sdlc-${{ github.event.issue.number || github.event.pull_request.number }}
      cancel-in-progress: false   # queue, don't cancel — pull-based model reads all state
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: a2sdlc dispatch
```

### Bot Filtering

Bot-authored comments are filtered by the `if:` condition — bot comments don't contain `@a2sdlc`. Bot label changes are intentional (stage transitions) and always processed. Single `a2sdlc` bot identity.

Since we use GitHub Actions (not App webhooks), ALL events fire including bot-generated ones. The workflow `if:` condition handles filtering.

### Platform Compatibility

| Capability | GitHub | Forgejo | GitLab (future) | Jira (future) |
|-----------|--------|---------|-----------------|---------------|
| Label triggers | `issues.labeled` | `issues.labeled` | Webhook -> trigger API | N/A (use status) |
| Comment triggers | `issue_comment` | `issue_comment` | Webhook -> trigger API, or cron | Cron or Jira Automation |
| PR review triggers | `pull_request_review` | `pull_request_review` (partial) | MR approval event | N/A |
| Concurrency | `concurrency` group | `concurrency` group | `resource_group` | N/A (CI-side) |
| Programmatic trigger | `repository_dispatch` | `workflow_dispatch` | Pipeline trigger API | N/A |

GitLab: no native CI triggers for MR comments. Future path: webhook-to-trigger bridge or cron sweep.

Jira: no CI integration. Future path: Jira Automation webhook or JQL-based cron sweep scoped to tracked tickets.

## Handover Pattern

### Comment Format

Each stage posts a handover comment on the issue (REVIEW posts on the PR). The format follows the existing progress comment structure with the handover marker added to the header:

```
### ✅ a2sdlc:spec

## Specification Complete

### Acceptance Criteria
1. ...

### Technical Approach
...

<details>
<summary>Stats</summary>

| Model | Branch | Context | Cost | Tokens | Duration | Turns |
|-------|--------|---------|------|--------|----------|-------|
| claude-sonnet-4-6 | feat/T-1 | 45k/200k (22%) | $0.72 | 45k in / 12k out | 2m 15s | 12/120 |

📌 0:42 — brainstorming invoked
📌 2:10 — requesting-code-review invoked

✅ Analyze requirements
✅ Write implementation plan
✅ Draft acceptance criteria

</details>
```

**Header**: `### ✅ a2sdlc:{stage}` — visible stage name at the top, doubles as the handover marker. During execution: `### ⏳ a2sdlc:{stage}`. On failure: `### 🚨 a2sdlc:{stage}`.

**Body**: human-readable stage output (spec, implementation report, review feedback).

**Footer**: existing collapsible Stats block — status bar table, milestones with timestamps, task checkpoints. No changes to the stats format.

The engine identifies handover comments by a regex pattern **compiled from the `StageName` enum**:

```python
HANDOVER_PREFIX = "a2sdlc:"
HANDOVER_PATTERN = re.compile(
    rf"{HANDOVER_PREFIX}({'|'.join(s.value for s in StageName)})"
)
```

Adding a new stage to `StageName` automatically updates the pattern. No hardcoded stage lists anywhere — `StageName` is the single source of truth for stage names, label names, handover markers, and routing.

### How Context Flows Between Stages

The issue's comment thread IS the context chain:

```
Issue body: "Add drag and drop support"
  Comment 1: ### ✅ a2sdlc:spec         [spec output + stats]
  Comment 2: ### ✅ a2sdlc:implement    [impl report + stats]
  PR Comment: ### ✅ a2sdlc:review      [review feedback + stats]
  Comment 3: Human: "@a2sdlc drag and drop broken"
  Comment 4: ### ✅ a2sdlc:implement    [fix report + stats]
```

The engine builds each stage's input by reading this thread:

1. **Find last handover** — scan issue comments AND PR comments using `HANDOVER_PATTERN` (compiled from `StageName` enum). Most recent match across both locations wins.
2. **Collect post-handover feedback** — all comments after the handover's timestamp that contain `@a2sdlc` or are PR review submissions. From both issue and PR.
3. **Collect PR state** (if PR exists) — diff summary, inline review comments with file/line metadata.
4. **Build agent prompt**:
   ```
   [ticket body — always included as ground truth]
   [last handover comment body — primary context]
   [feedback comments — what to address]
   [PR diff summary — current code state]
   ```
5. **Set system prompt hint** — "You are implementing a fresh specification" vs "You are addressing feedback."

This is one code path regardless of scenario. The handover is the cursor — everything before it is history, everything after it is new input.

### Avoiding the Telephone Game

Each handover is a checkpoint, not a summary of a summary. The ticket body is always included as ground truth. If the feedback loop runs 3 times, the agent sees: its most recent handover + the latest feedback. Context doesn't grow unboundedly.

## Human Gates

### Two Gates

```
SPEC ──(optional gate)──> IMPLEMENT ──> REVIEW ──(gate)──> MERGE
```

**1. Post-SPEC gate (optional, default: auto)**

- `auto`: advance to IMPLEMENT immediately
- `human`: stop. Human reviews spec. Proceed via `proceed` label or @a2sdlc comment.

If SPEC has questions:
- `self_answer: true` (default) — agent makes assumptions and notes them
- `self_answer: false` — waits for human answers (sets `needs-input` label)

**2. Pre-MERGE gate (default: human)**

After REVIEW passes, engine stops before MERGE. Human reviews code, tests, preview.

Gate signal per adapter:

| Adapter | Gate signal |
|---------|-----------|
| GitHub | PR approval (non-bot reviewer) |
| GitLab | MR approval |
| Jira (future) | Ticket status change |
| Label-based | `proceed` label on issue |

No gate between IMPLEMENT and REVIEW — review always runs automatically.

### Feedback During Human Gate

1. Human: "@a2sdlc drag and drop doesn't work, please fix"
2. Comment event triggers CI job (passes @mention filter)
3. Engine reads last handover → determines current stage
4. Engine collects feedback
5. IMPLEMENT runs (context = last handover + human feedback)
6. IMPLEMENT posts handover comment, sets `stage:review` label
7. New CI job: REVIEW runs, posts handover
8. Reaches pre-merge gate again
9. Human reviews again

Each step is a separate CI job.

## Feedback Collection

### What the Engine Collects

**From the issue:**
- All comments containing `@a2sdlc` posted after the last handover

**From the PR (if exists):**
- PR review submissions (all — reviews are inherently directed at the PR)
- PR inline comments containing `@a2sdlc`, with file path + line range metadata

**Format injected into agent context:**

```
## Feedback to Address

### PR Review by @jane (changes_requested)
General: "The error handling in the retry logic needs work."
- `src/a2sdlc/stages/implement.py` lines 45-52: "This swallows the original exception."
- `src/a2sdlc/stages/implement.py` line 78: "Missing timeout parameter."

### Issue Comment by @pm-bob
"When I test the preview, drag and drop doesn't work on mobile."
```

### What the Agent Produces

The agent fixes code and the engine posts a handover comment summarizing what was done. Individual replies to each feedback item are backlog.

### Noise Handling

@mention filter eliminates most noise. PR reviews (no @mention required) are all included — the agent skips emoji-only or "LGTM" reviews. A few wasted tokens is better than a fragile pre-filter.

## Feedback Routing

When a comment/review event fires, the engine determines the current stage from the last handover comment's `stage` attribute (authoritative source). If no handover exists, falls back to issue labels.

| Current stage | Feedback routes to |
|--------------|-------------------|
| No stage yet / SPEC | SPEC |
| IMPLEMENT or later | IMPLEMENT |

Feedback always re-enters through the natural entry point for the current pipeline position. If feedback during IMPLEMENT+ is truly a spec change, the agent flags it in its handover comment.

## Stages as Independent Products

### The Boundary

```
StageInput -> Stage -> StageResult + SideEffects
```

- **StageInput**: system prompt + user prompt + tool configuration
- **StageResult**: status, output text, metrics
- **SideEffects**: comments posted, labels changed, code pushed

The stage does not know whether it runs standalone or in a pipeline.

### Standalone Deployment

```yaml
# .github/workflows/review.yml
on:
  pull_request:
    types: [opened, synchronize]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: yoselabs/a2sdlc-review@v1
```

Wrapper reads PR diff, assembles context, calls stage, posts review comment, exits. No state machine, no labels.

### Pipeline Deployment

Engine assembles context (handover + feedback), calls stage, reads StageResult for routing, posts handover comment, sets label for next stage.

### Packaging

- `a2sdlc`: core package — stage definitions, adapter protocols, contracts, engine, state machine
- `a2sdlc-review`, `a2sdlc-implement`, etc.: thin Action wrappers (~50 lines) that import from core

## Concurrency

### CI Concurrency Groups

One group per ticket: `a2sdlc-${{ issue_number }}`. At most 1 running + 1 pending.

**Why dropped triggers are OK:** Pull-based model reads ALL current state. If 5 comments arrive and only 2 CI jobs run, the second job sees all 5 comments. The trigger is a wake-up signal — the data is in the comments.

### Dead-Zone Edge Case

If the last comment in a burst arrives after the pending slot is occupied and the running job finished reading, that comment waits until the next trigger.

Mitigations:
1. The pending job reads ALL comments since last handover, not since its trigger event.
2. Human can re-trigger by posting another @mention or applying a label.

This is a latency failure, not data loss. The comment is always readable on the next run.

### Self-Re-Trigger (Future)

End-of-run check: "did new @a2sdlc comments appear since I started?" If yes, fire `repository_dispatch`. Deferred — pull-based model is sufficient now.

## Review Stage

REVIEW posts feedback as a PR comment (like CodeRabbit) AND returns a structured verdict. Humans see review feedback as a normal PR comment. The engine uses the verdict for routing. Standalone mode ignores the verdict. The review comment uses the handover marker.

## Data Models

### FeedbackItem

```python
@dataclass
class FeedbackItem:
    id: str                              # Platform-native ID
    author: str                          # Username
    author_type: str                     # "human" | "bot"
    source: str                          # "issue_comment" | "pr_comment" | "pr_inline" | "pr_review"
    body: str                            # Comment text
    file_path: str | None                # For pr_inline only
    line_range: tuple[int, int] | None   # For pr_inline only
    created_at: datetime
```

### HandoverComment

```python
@dataclass
class HandoverComment:
    stage: StageName       # Which stage produced this
    run_id: str            # Unique run identifier
    body: str              # Full comment body (markdown)
    created_at: datetime   # Used as "since" timestamp for feedback collection
    location: str          # "issue" | "pr"
```

### PipelineEvent

```python
@dataclass
class PipelineEvent:
    key: str               # Ticket/issue key
    stage: StageName | None  # Target stage (from label) or None (for feedback)
    is_feedback: bool      # True for comment/review events
    pr_number: int | None  # If event is PR-related
```

## Configuration

```yaml
# a2sdlc.yaml
pipeline:
  gates:
    spec: auto           # auto | human
    merge: human         # auto | human
  spec:
    self_answer: true    # agent makes assumptions when questions arise
  review:
    max_cycles: 2        # circuit breaker for review loops
  trigger:
    mention: "@a2sdlc"  # configurable trigger phrase
```

## State Machine

```
SPEC ──(gate)──> IMPLEMENT ──> REVIEW ──(gate)──> MERGE
                    ^              |
                    └── changes ───┘
                    ^
                    └── @a2sdlc feedback
```

| From | Trigger | Next |
|------|---------|------|
| SPEC | complete, gate auto | IMPLEMENT |
| SPEC | complete, gate human | wait |
| SPEC | questions, self_answer on | SPEC (self-answer) |
| SPEC | questions, self_answer off | wait |
| IMPLEMENT | complete | REVIEW |
| REVIEW | approved, gate auto | MERGE |
| REVIEW | approved, gate human | wait for PR approval |
| REVIEW | changes_requested | IMPLEMENT |
| no stage / SPEC | @a2sdlc comment | SPEC |
| IMPLEMENT+ | @a2sdlc comment | IMPLEMENT |
| merge gate | PR approved | MERGE |

## Adapter Changes

### New Methods

- `ReviewAdapter.collect_pr_feedback(since: datetime) -> list[FeedbackItem]`
- `WorkAdapter.collect_issue_feedback(key, since: datetime) -> list[FeedbackItem]`
- `WorkAdapter.find_last_handover(key) -> HandoverComment | None`
- `ReviewAdapter.find_last_handover(pr_number) -> HandoverComment | None`

### Changed

- `parse_event()` handles `issue_comment`, `pull_request_review`, `pull_request_review_comment` events
- Context assembly uses handover algorithm
- REVIEW stage posts PR comment with handover marker
- Handover comment format standardized across all stages

### New CI Workflow Events

- `issue_comment.created` with @mention filter
- `pull_request_review.submitted` with bot filter
- `pull_request_review_comment.created` with @mention filter
- `concurrency` group per ticket
