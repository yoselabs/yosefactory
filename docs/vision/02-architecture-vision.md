# a2sdlc Engine — Architecture Vision

**Date:** 2026-04-22
**Status:** Draft for review
**Supersedes (when accepted):** aspirational parts of `docs/architecture.md`
**Companion to:** `docs/adr/` (0001 hexagonal-lite, 0003 evaluation-not-telemetry, 0004 import-linter)

This document is the **target shape** for the engine — the foundation we want the next 12–18 months of growth to land on. It does not describe current code; it describes what we're moving toward, why, and how we get there phase by phase.

`docs/architecture.md` remains the authoritative description of the **current** shape and its rules until the migration completes.

---

## 1. Why this document exists

The engine has outgrown its composition root. The architectural layering (domain / adapters / application) is healthy; the composition *inside* that layering has decayed. Twelve specific signals — enumerated in §3 — point to the same underlying cause: the engine has several distinct bounded contexts (ingress, gating, session, agent invocation, effects, observability, evaluation) that are only partially named, so new concerns keep landing in `pipeline/dispatch.py` by default.

This document:

1. Inventories the use-cases the foundation must fit (current + 12–18 months).
2. Names the growth vectors that will pressure the design.
3. Declares the properties a good foundation must have.
4. Evaluates fifteen architectural patterns against those properties.
5. Picks a foundation and explains why.
6. Shows what concretely changes.
7. Lays out a phased, reversible migration.

The foundation is not a rewrite. It is a sequence of targeted moves against a clear target shape.

---

## 2. Use-case inventory — what the foundation must fit

Scoped to present reality + credibly-anticipated 12–18 months. Sources: current code, `TODO.md`, existing design docs under `docs/superpowers/specs/`, and the eval-system / shaping plans referenced in project notes.

### 2.1 Event ingestion — 15+ trigger shapes

Today: GitHub `issues.labeled / issue_comment / pull_request.labeled / pull_request_review.submitted / pull_request_review_comment / issues.closed`; Jira via dispatcher (transition, comment, webhook); local `.a2sdlc/ticket.md`; CLI `run-stage`.
Planned: Linear, GitLab, ADO, Gitea, scheduled (cron), manual retry, cross-repo (issue in A, code in B), branch pushes for deploy, epic fan-out.

### 2.2 Stage catalogue — growing from 4 to 8+

Today: `SPEC`, `IMPLEMENT`, `REVIEW`, `MERGE`.
Planned: `DEPLOY`, `STALENESS_CHECK`, `EPIC_SHAPING`, `RELEASE_NOTES`, `SECURITY_SCAN`, and a `REVIEW → SPEC` rejection path. Mix of AI and deterministic.

### 2.3 Quality gates

Today: single `make check` post-IMPLEMENT.
Planned: diff-coverage threshold, security audit, custom per-repo gates. Gates are **effects**, not stages — they apply within/after a stage.

### 2.4 Feedback routing — four sources, stage-sensitive

Issue comments (@mention gated), PR review submissions, PR inline comments, directive changes. Routing depends on `current_stage` from handover, not event alone. Three active routing rules today (`feedback_routing`, `next_stage`, inline "proceed" branch).

### 2.5 Progress / observability — 5 active sinks, more coming

Today: progress comment (per platform debounce/truncation), GH Actions log, rich console, MLflow (nested runs + metrics + artifacts), dispatcher HTTP (Jira bridge).
Planned: two-layer content (ticket summary + PR full body), OpenTelemetry, web dashboard, Datadog.

### 2.6 State / session / idempotency

`TicketState` on branch (`state.json`); deterministic session IDs for Claude SDK; idempotency via `stage_run_id`; parallel A/B via `run_id` scoping. Ordering invariant today: branch must be checked out before state is read.
Planned: orphan-branch state storage, dispatcher KV for Jira.

### 2.7 Config resolution — 5-layer resolution, inline today

`StageConfig` defaults → `project.stage_overrides` → directive overrides → label overrides → env. Currently merged inline in dispatch. Needs a `ResolvedConfig` materialized once.

### 2.8 Branch / PR lifecycle

Setup (idempotent), seed empty commit (GH rejects empty-diff PRs), draft PR on SPEC start, update on IMPLEMENT done, mark-ready on REVIEW approval, squash-merge on MERGE, cleanup runtime artifacts from base.
Planned: sync-with-base before merge, rebase strategy option.

### 2.9 Comment lifecycle — platform concerns significant

Begin once per stage, throttled updates (platform-specific debounce), finalize once (must-succeed with retry). Per platform: Jira 32K + ADF + 20 writes/2s; GitHub 65K + 180/min + markdown; GitLab 1MB + 2K/min; ADO 1M; Linear unknown; Forgejo unlimited.

### 2.10 Circuit breakers

Review cycles, cost ceiling per ticket.
Planned: max-duration per stage, rate limits (tickets/day/user), org-level budgets.

### 2.11 Directives

`[a2sdlc key=value]` in ticket body. Today: `base`, `gate:merge`, `gate:spec`.
Planned: `effort`, `budget`, `model`, `skills-allowlist`.

### 2.12 Composition modes — 3 today, more coming

Local (`run-stage`), GH-native (Mode 2), Jira-dispatcher (Mode 1). Mode selection today is ambient (`DISPATCHER_URL` env var), not config-driven — a latent problem.
Planned: self-hosted service, managed SaaS, multi-tenant.

### 2.13 Evaluation harness

Today: MLflow nested runs + `quality.log` artifact.
Planned: fixture monorepo, CI-driven eval on engine PRs, pen-tester / BA evaluator workflows.

### 2.14 Agent providers

Today: Claude Agent SDK only.
Planned: Gemini / GPT via unified runner; local models via LiteLLM; multi-model A/B.

### 2.15 Multi-agent

Today: one agent per stage.
Planned: sub-agents within REVIEW (pen-tester); shaping agent that fans out to multiple tickets.

### 2.16 Priority order — near-term composition modes

Not all modes are equal. Current priority:

1. **GitHub Issues + GitHub repo** (Mode 2 today) — the hot path; must remain working at every migration phase.
2. **Jira Issues + GitHub repo** (Mode 1 today) — additive; uses dispatcher service.
3. **Fully local execution** — developer-loop only; file-backed adapters.

Every phase of the migration preserves #1. #2 and #3 are validated at phase boundaries, not inside each phase.

### 2.17 Native code review on GitHub — line-level comments

Today: `ReviewAdapter.post_review(pr_number, body, verdict)` posts a single general review comment.
Near-term: the REVIEW stage must post **line-level inline comments** on specific files/lines — GitHub's native code-review surface, not a single aggregate body. Reviewers expect to see per-line threads, not a wall of text.

Architectural consequence:
- `ReviewAdapter` gets `post_inline_comments(pr, comments: list[InlineComment])` where `InlineComment = (file, line_range, body, side)`.
- The REVIEW stage handler's `StageOutcome` carries a structured review payload, not just markdown.
- New `Effect` variant: `PostInlineReview(pr, summary, verdict, comments: list[InlineComment])`.
- Interpreter arm applies summary + per-line comments as one API operation (GitHub supports a single "create review with comments" request).

### 2.18 Subtask-driven execution with parent-branch merges

Near-term: epic/parent tickets fan out to child tickets; each child runs the normal pipeline; children merge into the **parent's branch**, not base; parent's MERGE consolidates to base.

Architectural consequences:
- **Branch strategy** becomes hierarchical. Today: `a2sdlc/<key>` off `main`. Near-term: child branch `a2sdlc/<parent>/<child>` off parent branch.
- **TicketState** gains `parent_key: str | None`, `children: list[str]`.
- **Transition table** gains a parent-side state: "epic waiting on children," "all children merged → run parent MERGE."
- **Event ADT** gains a `ChildCompletedEvent(parent_key, child_key)` variant.
- **New stage:** `EPIC_ORCHESTRATE` (or similar) — produces `CreateChildTicket` effects, checks `AllChildrenMerged` guard, emits `MergeParent` when ready.
- **Concurrency:** children can run in parallel or sequentially; orchestrator decides via directives.

This is a first-class pattern, not a bolt-on. The vision's stage-handler + effects split accommodates it — adding `EPIC_ORCHESTRATE` is one new handler + a handful of effect variants.

### 2.22 Subagents — flat event stream with agent prefix

Claude Agent SDK supports subagents via `AgentDefinition` + the `Agent` tool. **SDK constraint: subagents cannot spawn subagents** (max depth = 2). Subagents can run in parallel (`background: true`). Messages from within a subagent have `parent_tool_use_id` set — our correlation key.

**Event model:** flat stream, not tree. Every event carries `agent: str` — either `"root"` (stage main agent) or the subagent name (e.g., `"pen-tester"`). Parallel subagents produce interleaved events distinguishable by prefix:

```
[10:23:17] [root]                📖 Read src/api.py
[10:23:20] [root]                🤖 Spawn pen-tester, performance-reviewer (parallel)
[10:23:22] [pen-tester]          📖 Read src/auth.py
[10:23:22] [performance-reviewer] 🔧 Grep "N+1"
[10:23:25] [pen-tester]          💭 "unchecked input in /login"
[10:23:28] [performance-reviewer] ✓ done ($0.03, 4 turns)
[10:23:30] [pen-tester]          ✓ done ($0.05, 6 turns)
[10:23:31] [root]                📝 Write review-findings.md
```

This matches the SDK's model: `parent_tool_use_id` gives us the label; no deeper hierarchy exists.

**New event variants** (`domain/progress.py`):
```python
class SubagentStart(BaseModel):
    kind: Literal["subagent_start"] = "subagent_start"
    agent: str                  # subagent name
    parent_agent: str           # "root" or outer agent name (always "root" given depth=2)

class SubagentEnd(BaseModel):
    kind: Literal["subagent_end"] = "subagent_end"
    agent: str
    summary: str
    cost_usd: float
    turns: int
```

Every existing event adds `agent: str = "root"` field.

**Declarative subagent config** lives in the workflow YAML per stage:
```yaml
workflow:
  stages:
    review:
      subagents:
        pen-tester:
          description: "Security-focused review. Use for auth, input validation, secrets."
          prompt_file: ./prompts/subagents/pen-tester.md
          tools: [Read, Grep, Glob]
          model: claude-sonnet-4-6
        performance-reviewer:
          description: "Performance review for hot paths."
          prompt_file: ./prompts/subagents/performance-reviewer.md
          tools: [Read, Grep, Glob, Bash]
          background: true    # runs in parallel with other subagents
```

MLflow: each subagent invocation becomes a `mlflow.start_span(name=f"subagent:{agent}")` nested under the stage's span. Parallel subagents = sibling spans at the same level.

### 2.23 Rate limiting / backpressure — self-healing via label + sweep

Repo-level rate limits (per-hour cost cap, per-hour concurrency cap) must **not** cancel events permanently — they must **defer** events for later pickup when capacity returns.

**Pattern — "park and sweep":**

1. When a dispatch is rate-limited: mark ticket with `rate_limited` label; write `rate_limited_until: <ISO timestamp>` to `TicketState`. Exit cleanly, do NOT re-label as blocked.
2. A scheduled workflow (`on: schedule: cron: '0 * * * *'`) runs hourly. It lists all tickets with `rate_limited` label, checks each `TicketState.rate_limited_until`, and re-triggers dispatch for any whose window has cleared.
3. CI concurrency group prevents duplicate dispatches.

This is the self-healing primitive. No new engine infrastructure beyond a new `RateLimitDeferred` effect and the scheduled sweep workflow in the consumer repo's CI. Not for today; shape defined so the door is open.

### 2.24 Credential profile — two GitHub Apps (worker + reviewer)

Branch protection on `main` often requires reviews from a user who is not the PR author. Today the engine self-approves, which is brittle. The clean fix is **two distinct GitHub Apps**:

- **`a2sdlc-worker`** — does everything except review: opens PRs, commits, sets labels, merges after approval. Scoped: `contents:write`, `issues:write`, `pull_requests:write`.
- **`a2sdlc-reviewer`** — only reviews and approves PRs. Scoped: `contents:read`, `pull_requests:write`. Distinct App = distinct GitHub identity = counts as a real reviewer under branch protection.

**Declarative per-stage:**
```yaml
workflow:
  stages:
    spec:
      credential_profile: worker
    implement:
      credential_profile: worker
    review:
      credential_profile: reviewer     # uses the reviewer App's installation token
    merge:
      credential_profile: worker
```

Engine fetches the appropriate installation token per stage. CI provides both App IDs + private keys as secrets.

**GitLab equivalent:** two **Project Access Tokens** with different roles (Reporter+Approver for reviewer, Developer for worker). GitLab doesn't have GitHub Apps but the capability model is equivalent.

**Bitbucket:** out of scope.

### 2.25 Cancellation propagation — reserved slot

On ticket close / label-removed / PR-closed: a **cleanup CI workflow** triggered by that event enumerates running CI jobs via GH API (`gh run list --repo ... --status=in_progress`) and cancels those matching the ticket's concurrency group.

New effect (reserved): `CancelRunningJobs(ticket_key)`. Interpreter calls the GH API. Not for today.

### 2.26 Engine self-observability vs pipeline observability

Engine components needing runbooks:
- **Dispatcher service** (Mode 1) — uptime, webhook delivery, runs table integrity.
- **MLflow tracking server** — if self-hosted.
- **Scheduled sweep workflow** (§2.23) — last run time, tickets swept per run.

Each gets a runbook in `docs/runbooks/` per process doc step (6). Not a new engine feature.

### 2.27 Revert flow — reserved slot for `REVERT` stage

When a merged PR breaks main: label the merged PR with `a2sdlc:revert`. Engine triggers a new `REVERT` stage that creates a revert PR, runs an expedited pipeline (skip SPEC, minimal IMPLEMENT, fast REVIEW, auto-MERGE). Reserved slot; not for today.

### 2.19 Local agent isolation via git worktrees

Near-term: multiple agents on the same repo can run concurrently in local mode. Each agent runs in its own git worktree.

Architectural consequences:
- **New `GitAdapter` impl:** `WorktreeGitAdapter` — creates `.a2sdlc/worktrees/<run_id>/` per run, checks out the run's branch there, executes all git ops in that worktree, destroys on completion.
- **`project_root` in `RunContext`** becomes per-run, not per-CLI-invocation. The runner's `cwd` points at the worktree, not the repo root.
- **Agent isolation:** each worktree has its own working tree; parallel runs cannot stomp on each other's files.
- **Cleanup:** `Effect.CleanupWorktree(run_id)` at pipeline end. Must be idempotent and survive crashes (orphaned worktrees get swept by a `GitAdapter.prune_worktrees()` on next invocation).

### 2.20 Security embedded in every stage (shift-left)

Near-term: security is a cross-cutting concern **inside** each stage, not a separate stage.

- **SPEC** — threat modeling, abuse-case surfacing, compliance check against policy.
- **IMPLEMENT** — static analysis, dependency audit, secrets scan during and after changes.
- **REVIEW** — security-focused checks in addition to quality; optional pen-tester sub-agent.
- **MERGE** — policy-gate enforcement (no secrets, no failing scans, no disallowed licenses).

Architectural consequences:

- **Shared `security/` module** exposed to every stage handler — checks composable across stages, not duplicated.
- **New `Effect` variants:** `RunSecurityScan(tool, config)`, `AssertNoSecrets(paths)`, `CheckLicensePolicy()`. Each has an interpreter arm that can veto via `MarkBlocked`.
- **Security findings become structured** and flow through the same channels as review comments — inline PR comments from §2.17 carry `severity` and `cwe`.
- **Per-stage security config** in `.a2sdlc/config.yaml` so teams can tune strictness per stage.
- **The quality gate stays separate** (`make check`) — security is "did we introduce risk," not "did the tests pass."

This fits the effects model cleanly: security is just more effects, emitted by handlers, applied by the interpreter.

### 2.21a Stages runnable standalone — per-stage products

Near-term: **every stage must be invokable independently**, not only as part of the full pipeline. A user must be able to:

- Run `a2sdlc review <pr-url>` against a PR without a ticket ever existing — as a Copilot-reviewer / CodeRabbit / bugbot alternative.
- Run `a2sdlc spec <ticket-url>` to produce a spec document without triggering implementation.
- Run `a2sdlc implement <ticket-url>` against a spec without triggering review.

This is not a new CLI convenience. It is a **product-surface commitment**: each stage ships as a standalone tool that competes with point products at its own stage.

Architectural consequences — the factory is already shaped for this, with one rule we must not violate:

- **No implicit cross-stage coupling.** A `StageHandler` must declare everything it needs in its inputs. It may NOT assume "a prior stage ran and put X on disk." If it depends on a spec artifact, it takes a path to that artifact (or None).
- **The effects interpreter has a "standalone" mode.** Transitions (`SetCurrentStage`, `Transition`) become no-ops. Terminal effects (`CommentFinalize`, `PostReview`, `CommitAndPush`) still fire.
- **Each stage becomes a separate CLI entry point.** `a2sdlc review`, `a2sdlc spec`, `a2sdlc implement`. All delegate to the same handler as the full pipeline uses. The handler does not know whether it's running standalone or in-pipeline.
- **Each stage can ship as a GitHub Action** (`yoselabs/a2sdlc-review@v1`). One Action per stage. Teams adopting only one stage don't install the whole engine.
- **Pipeline-only effects** (transition wiring, stage-to-stage handover comments) are emitted by the *orchestrator*, not the handler. The handler emits only its own outcome-effects. The pipeline adds orchestration effects on top.

This fits the product vision's factory frame: the factory owns the assembly line, but each machine on the line **can also be rented standalone**. That's an additional product surface, not a different architecture.

### 2.21 Backpropagation — requirements adjust after early implementation

Near-term: reality from IMPLEMENT must flow back into SPEC. When a child story's implementation reveals that the parent epic's spec had wrong assumptions, the engine should reshape remaining work — not wait for a human to notice.

- After the first 1–2 child stories ship, discoveries (missed edge cases, wrong estimates, incompatible design assumptions) trigger a **structured drift signal** to the parent epic.
- The parent's SPEC stage can be re-invoked with the drift signal + accumulated child outcomes as context.
- Workload rebalances — some remaining children expand, split, or get cancelled.

Architectural consequences:

- **New `Event` variants:** `RequirementsDriftEvent(parent_key, child_key, findings)`, `WorkloadReestimateEvent(parent_key, remaining, new_shape)`.
- **Parent `TicketState` grows:** `revisions: int`, `child_outcomes: dict[str, ChildOutcome]`, `last_reestimate_at: datetime | None`.
- **New `Effect` variants:** `TriggerSpecRefresh(parent_key, context)`, `UpdateChildPriority(...)`, `SplitChildTicket(...)`, `CancelChild(key, reason)`.
- **`EPIC_ORCHESTRATE`** (from §2.18) is the natural home — its `effects()` emits `TriggerSpecRefresh` when drift exceeds a configurable threshold.
- **Effects-as-audit-log (Q2) becomes load-bearing** — backpropagation needs an auditable trail of "what was decided when, and what new information changed it." Reinforces the recommendation for Q2 (persist effects).
- **Config directive:** `[a2sdlc reestimate=after-2-children]` lets a team tune how aggressively the engine reconsiders.

This closes the SDLC loop: stages are not one-way; the engine supports adaptive planning natively.

---

## 3. Twelve signals of architectural decay

The surface symptom is that `pipeline/dispatch.py` is 499 lines with seventeen numbered steps. That is one signal. Eleven others point the same direction:

1. **Two composition roots, diverged.** `cli/dispatch.py` (Mode 1/Mode 2 env-branch) and `cli/run_stage.py` build `DispatchContext` very differently. `adapters/factory.py` is half-finished (local variants only).
2. **Telemetry framed twice.** `evaluation/tracked_run.py` wraps dispatch from outside; dispatch also opens `telemetry.session().stage()` inside. The `telemetry or NoopTelemetry()` fallback exists solely to avoid double-wrap.
3. **Subscriber registration split across layers.** `assembly/wire.py` adds some subscribers; dispatch adds the comment subscriber later via an injected factory. Timing is implicit.
4. **`PipelineEvent` is a bag of optional flags** (`is_closed`, `is_feedback`, `trigger_stage`, `pr_number`). Routing triangulates from booleans where a discriminated union would eliminate branching.
5. **State / branch / PR / comment co-vary but are separately managed.** "Branch setup before state read" is undeclared invariant.
6. **Four layers of override resolve inline.** Directives → gate config → stage overrides → project config. No `ResolvedConfig`.
7. **Error handling is copy-pasted.** Four near-identical blocks: `comment.finalize(error) → commit_push → mark_blocked → DispatchResult(blocked=True)`.
8. **Stages are data; stage *behavior* lives in dispatch.** MERGE is special-cased inline; SPEC's "seed branch + empty commit + draft PR" prelude is inline; REVIEW's "append PR context + post_review" is inline.
9. **Three different "routing" rules, three homes.** `stages.next_stage`, `feedback_routing.resolve_target_stage`, inline proceed-branch.
10. **`domain/progress_format.py` is 298 lines** — rendering dressed as domain to avoid circular imports.
11. **`DispatchResult.output` leaks raw agent text** all the way to CLI, where MLflow serializes it.
12. **Implicit bounded contexts.** Ingress, gating, session, agent, effects, observability, evaluation exist conceptually but only some are named packages. Unnamed ones pile into `dispatch.py`.

---

## 4. Growth vectors

Ten axes will put pressure on the design over the next 18 months. Any architecture that doesn't address all ten is a temporary solution.

1. **Trackers:** 1 → 5+ (GitHub, Jira, GitLab, Linear, ADO, Forgejo).
2. **Stages:** 4 → 8+.
3. **Event types:** 6 → 15+ (scheduled, cross-repo, manual retry).
4. **Observability sinks:** 5 → 8+ (OTEL, web UI, Datadog).
5. **Quality gates:** 1 → N per repo.
6. **Agent providers:** 1 → 3+ (Claude, Gemini, GPT, local via LiteLLM).
7. **Composition modes:** 3 → 5+ (service, SaaS).
8. **Evaluation:** offline → production-grade eval harness.
9. **Concurrency:** per-ticket → multi-run per ticket (A/B) → multi-tenant.
10. **Durability:** ephemeral CI → crash-recoverable → resumable mid-stage.

---

## 5. Properties the foundation must have

| # | Property | Definition |
|---|---|---|
| P1 | Independent stage addition | New stage = 1 file, zero dispatch edits |
| P2 | Independent platform addition | New adapter = zero domain/pipeline edits |
| P3 | Testable in isolation | Any unit testable without platforms or real AI |
| P4 | Decision-point observability | Every branch emits structured data |
| P5 | Failure-local | Subscriber crash ≠ run crash; effect error doesn't corrupt state |
| P6 | Effects auditable | Enumerate what side-effects any run took |
| P7 | Thin composition root | Dispatch does composition only |
| P8 | Mode-agnostic engine | Engine doesn't know Mode 1 vs Mode 2 |
| P9 | Durable / resumable | Crash mid-stage → clean resume (long-term) |
| P10 | Eval-native | Runs replayable, variants comparable, bugs reproducible |

Current codebase against P1–P10: **P1 ⚠️ · P2 ✅ · P3 ⚠️ · P4 ⚠️ · P5 ✅ · P6 ❌ · P7 ❌ · P8 ❌ · P9 ❌ · P10 ⚠️**.

---

## 6. Patterns evaluated

Fifteen candidate patterns, scored against P1–P10. ✅ strong / ⚠️ partial / ❌ weak.

| # | Pattern | Core idea | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | P9 | P10 | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Hexagonal-lite (current) | Ports & adapters + two-layer domain/app split | ⚠️ | ✅ | ⚠️ | ⚠️ | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️ | Keep the layering — insufficient alone |
| 2 | Pipe-and-filter | Composition root as linear pipeline of steps | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ❌ | ⚠️ | **Adopt** |
| 3 | Explicit state machine (xstate) | States + transitions + entry/exit | ⚠️ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ✅ | ⚠️ | ⚠️ | Skip — `next_stage` already pure |
| 4 | Strategy for stages | Stage = handler class | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ❌ | ⚠️ | ✅ | ❌ | ⚠️ | **Adopt** |
| 5 | Effects-as-data + interpreter | Redux/Elm — pure effect descriptors | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | **Adopt — the big unlock** |
| 6 | Pipeline middleware | Chain of responsibility around core | ⚠️ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | **Adopt** |
| 7 | Temporal / Cadence | Durable workflow engine | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Mental model yes, SDK no |
| 8 | Event-sourced + CQRS | Write emits events; read rebuilt | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | Skip — no separate read path |
| 9 | Actor model | One actor per ticket | ⚠️ | ✅ | ⚠️ | ⚠️ | ✅ | ❌ | ⚠️ | ⚠️ | ⚠️ | ❌ | Skip — CI concurrency group already does this |
| 10 | Functional core / imperative shell | Pure decision logic, thin I/O edge | — | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | **Adopt as discipline** |
| 11 | Vertical slice / feature folders | Feature cohesion per folder | ✅ | ⚠️ | ✅ | ⚠️ | ✅ | ❌ | ⚠️ | ⚠️ | ❌ | ⚠️ | Skip — stages aren't independent features |
| 12 | DDD bounded contexts | Multiple contexts with own models | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | Partial — engine+dispatcher IS two contexts |
| 13 | Declarative DAG (Dagster/Airflow) | Stages as graph nodes | ⚠️ | ✅ | ⚠️ | ✅ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ✅ | Skip — pipeline has loops, not a DAG |
| 14 | LangGraph | Agent workflow with checkpointer | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | ✅ | ⚠️ | Skip — own the vocabulary |
| 15 | Inngest / Restack (SaaS durable) | Managed durable workflow | — | — | — | — | — | ✅ | — | — | ✅ | ⚠️ | Watch, not now |

**Combination adopted: 1 + 2 + 4 + 5 + 6 + 10.** Rationale: the existing hexagonal layering stays; composition root becomes a pipe-and-filter; stages become strategies; side effects become data; cross-cutting concerns become middleware; functional-core discipline permeates all of it. Temporal provides the vocabulary (workflow / activity / side-effect boundary) without its SDK; if durability (P9) ever becomes load-bearing, Temporal slot-fits.

---

## 7. The target shape

### 7.1 Package layout

Twelve packages. One responsibility each. No overlap.

```
packages/engine/src/a2sdlc/
├── domain/              # pure types, zero I/O (smaller than today)
├── adapters/            # pluggable I/O — work / review / git / runner / subscriber
├── ingress/             # event parsing + intent resolution + directive parsing
├── gating/              # preconditions + circuit breakers + idempotency guards
├── session/             # TicketState + branch + PR + comment lifecycles
├── agent/               # runner + prompt assembly + follow-up retry + extract_result
├── stages/              # StageHandler implementations (one per stage)
├── effects/             # Effect ADT + interpreter
├── middleware/          # cross-cutting wrappers — retry, idempotency, logging, telemetry
├── observability/       # progress bus + subscribers + event taxonomy + rendering
├── evaluation/          # MLflow + quality gate + future eval harness (see ADR 0003)
├── config/              # loading + resolution (layered overrides → ResolvedConfig)
├── cli/                 # composition roots — one per mode, all thin
└── pipeline.py          # composition — ~60 lines, the ONE broad-import module
```

### 7.2 Three load-bearing type contracts

**StageHandler (Strategy)** — every stage conforms to this shape.

```python
class StageHandler(Protocol):
    name: StageName
    valid_statuses: frozenset[StageStatus]

    def preconditions(self, ctx: RunContext) -> BlockReason | None:
        """Pure. Return blocking reason or None."""

    async def execute(self, ctx: RunContext) -> StageOutcome:
        """I/O boundary — only this method touches adapters."""

    def effects(self, ctx: RunContext, outcome: StageOutcome) -> list[Effect]:
        """Pure. Map outcome → list of effects."""
```

MERGE becomes a regular handler whose `execute()` does deterministic git+PR ops — no special casing in dispatch.

**Effect (algebraic data type)** — side effects are data.

```python
Effect = (
    # Session lifecycle
    StateWrite(state: TicketState) |
    CommentStart(stage: StageName) | CommentFinalize(body: str) |
    CreateDraftPR(branch, base, key) | UpdatePR(...) | MergePR(pr) | PostReview(pr, verdict, body) |
    SetCurrentStage(stage) | MarkBlocked(reason) | MarkDone | MarkNeedsInput |
    # Git
    CommitAndPush(paths, message) | CleanupBase(base) |
    # Control flow
    Transition(next: StageName | None) |
    # Quality / evaluation
    RunQualityGate(command: str) | LogMetric(key, value) | LogArtifact(path) |
    # Future
    NotifySlack(...) | CreateChildTicket(...) | ...
)
```

Handlers produce effects; the interpreter applies them against adapters. Effects are pure data: logged, replayable, auditable.

**Event (sum type replacing flag-bag)** — event shape is explicit.

```python
Event = (
    TicketClosedEvent(key) |
    LabelTriggerEvent(key, stage: StageName, pr_number: int | None) |
    FeedbackEvent(key, pr_number: int | None, source: FeedbackSource) |
    ProceedEvent(key, current_stage: StageName | None) |
    SkipEvent(reason)
)
```

Routing becomes a `match` statement, not branches triangulating from boolean flags.

### 7.3 Composition root — the whole of `pipeline.py`

```python
async def dispatch(ctx: RunContext) -> DispatchResult:
    event = ctx.ingress.parse()
    match event:
        case SkipEvent(reason):
            return DispatchResult.skipped(reason)
        case TicketClosedEvent(key):
            return await ctx.effects.apply([MarkDone(key)])

    if reason := ctx.gating.check(event, ctx):
        return DispatchResult.blocked(reason)

    intent = ctx.ingress.resolve_intent(event, ctx)
    handler = ctx.stages[intent.stage]

    if reason := handler.preconditions(ctx):
        return DispatchResult.blocked(reason)

    async with ctx.observability.stage(intent.stage, ctx.run_id):
        outcome = await handler.execute(ctx, intent)
        effects = handler.effects(ctx, outcome)
        return await ctx.effects.apply(effects)
```

Every numbered step from today's 499-line dispatch becomes a call into a named package.

### 7.4 Middleware onion

Cross-cutting concerns wrap the pipeline as onion layers, not in-pipeline branches:

```
idempotency(
  retry(
    logging(
      telemetry(
        pipeline.dispatch
      )
    )
  )
)
```

Order is declared in one place (`pipeline.py` or `cli/`), making middleware ordering visible instead of implicit.

### 7.5 Mode-agnostic composition root

Today: `cli/dispatch.py` branches on `DISPATCHER_URL`.
Target: `cli/main.py` reads config + env into a `CompositionProfile` that names the adapters, subscribers, and middleware to activate. Mode selection becomes declarative, not ambient.

```python
profile = resolve_composition_profile(env, config)
# {
#   tracker:  "github_issue" | "gitlab_issue" | "jira" | "local_file",
#   ingress:  "github_event_path" | "gitlab_ci_payload" | "workflow_input",
#   review:   "github" | "gitlab" | "local_noop",
#   git:      "local" | "worktree",
#   progress: ["gh_comment" | "gl_comment", "mlflow", ...],
#   middleware: ["idempotency", "retry", "logging", "telemetry"],
# }

adapters    = build_adapters(profile)
subscribers = build_subscribers(profile)
middleware  = build_middleware(profile)
```

`tracker` (which domain model) and `ingress` (which transport delivers events) are deliberately split — they vary independently. GitHub-tracker + GitHub-Actions-ingress is one combination; Jira-tracker + workflow-input-ingress (via dispatcher) is another.

`adapters/factory.py` becomes the single adapter builder. `assembly/wire.py` folds into `observability/wire.py` (subscribers only). Mode 1 / Mode 2 / local are three *profiles*, not three code paths — and the terms "Mode 1" / "Mode 2" disappear from engine code after P6.

### 7.6 Dispatcher as a separate bounded context

The dispatcher (`packages/dispatcher/`) is a distinct bounded context from the engine. It has its own domain events, translator, and state. It talks to the engine only via:
- **Input:** workflow input (the engine reads from `WorkflowInputReader`).
- **Output:** HTTP POST to `/runs/{id}/events` (the engine publishes via `DispatcherEventSubscriber`).

**Rule:** the dispatcher is the *only* other a2sdlc bounded context. Everything inside `packages/engine/` is one context. Don't create more engine-internal contexts — the domain doesn't warrant it (per ADR-0001).

---

## 8. Concrete deltas — what changes

| Concern | Today | Target |
|---|---|---|
| Event shape | `PipelineEvent` with 4 optional flags | `Event` sum type |
| Routing | 3 rules in 3 places | `ingress.resolve_intent` single function |
| Config resolution | inline in dispatch (5 layers) | `ResolvedConfig` materialized once |
| Stage behavior | inline in dispatch; stages are config | `StageHandler` per stage, config inside |
| Error shape | 4 copy-pasted blocks | 4 effect variants + interpreter arms |
| Side effects | direct adapter calls in dispatch | `Effect` ADT + interpreter |
| Composition roots | 2 divergent (cli/dispatch vs cli/run_stage) | 1, selected by `CompositionProfile` |
| Telemetry framing | double-layered | single middleware layer |
| Subscriber timing | split (wire + dispatch) | all in `observability/wire` |
| `progress_format.py` (298 LOC) | in `domain/` | moved to `observability/render/` |
| Ordering invariants (branch→state) | implicit | explicit guard in `gating/` |
| Idempotency | inline check | middleware |
| Retry | inline `must_succeed` | middleware (or effect-level) |

### What disappears

- `pipeline/feedback_routing.py` — folds into `ingress/intent.py`.
- `pipeline/breakers.py` — folds into `gating/`.
- `pipeline/context.py` — folds into `agent/context.py`.
- `assembly/wire.py` — splits: adapters → `adapters/factory.py`; subscribers → `observability/wire.py`.
- `evaluation/tracked_run.py` — folds into middleware.
- `domain/progress_format.py` — moves to `observability/render/`.
- Mode-1/Mode-2 branching in `cli/dispatch.py` — replaced by profiles.

### What gets promoted

- `stages/*.py` — from thin config objects to full behavior (handlers).
- `effects/` — new package, ~2 files.
- `middleware/` — new package, ~5 files.
- `ingress/` — new package (event parse + intent resolve + directive parse).
- `gating/` — new package (preconditions + breakers + idempotency).

---

## 9. Scaling against the growth vectors

How each of the ten growth vectors is absorbed by the target shape — without structural change:

| Vector | Absorption strategy |
|---|---|
| **1. Trackers** | Add `adapters/work/<name>.py` + `adapters/review/<name>.py`. Factory selects via profile. Zero engine edits. |
| **2. Stages** | Add `stages/<name>.py` handler. Register in `STAGES`. Transition table adds one entry. Zero dispatch edits. |
| **3. Event types** | Add variant to `Event` ADT; add arm in `ingress.parse` + `ingress.resolve_intent`. Type system forces completeness. |
| **4. Observability sinks** | Add `Subscriber` impl; register in profile. Failure-isolated via existing `_failed` set. |
| **5. Quality gates** | Add `Effect` variant (`RunDiffCoverage`, `RunSecurityScan`); interpreter arm; stages emit the effect. |
| **6. Agent providers** | Add `StageRunner` impl; adapter factory selects by profile. `runner/claude_sdk.py` alongside `runner/litellm.py`. |
| **7. Composition modes** | Add `CompositionProfile`. Engine doesn't change. Self-hosted service = same engine invoked by a worker consuming a queue. |
| **8. Eval harness** | Effects are data → replayable. `RunContext` is serializable → reproducible. MLflow already one middleware layer. Add `EvalHarness` feeding fixtures through the pipeline. |
| **9. Concurrency / multi-tenant** | `RunContext.tenant_id` + `run_id` first-class. Idempotency middleware keys on them. Nothing else touches global state. |
| **10. Durability** | Add `Checkpointer` middleware that persists `RunContext` between pipeline steps. Effects-as-data means replay is safe (idempotent interpreter arms). |

No growth vector forces a structural change. Every one is additive.

---

## 10. Migration pathway

Eight phases. Each phase ships; each is reversible; each leaves the system green.

| Phase | Goal | Effort |
|---|---|---|
| **P1 — Model the domain honestly** | `Event` ADT, `ResolvedConfig`, `BlockReason`, and `TicketState` schema + versioning contract (ADR-0005). Explicitly includes parent/children fields to unblock N2. No behavior change; existing code reads new types. | 3 days |
| **P2 — Stage handlers** | Promote `stages/*.py` to `StageHandler`. Move stage-specific logic out of dispatch. MERGE becomes a regular handler. | 1 week |
| **P3 — Effects ADT + interpreter** | Stages return `list[Effect]`. Interpreter applies them. Copy-pasted error blocks collapse into interpreter arms. | 1 week |
| **P4 — Pipe-and-filter dispatch** | Break remaining dispatch into named steps in `ingress/`, `gating/`. Dispatch ≈ 60 lines. | 3 days |
| **P5 — Middleware layer** | Extract retry, idempotency, logging, telemetry to middleware. Kill double telemetry-framing. | 3 days |
| **P6 — Unified composition** | `CompositionProfile` + finished `adapters/factory.py`. Kill `DISPATCHER_URL` env-branch. One `cli/main.py`. | 3 days |
| **P7 — Rename & relocate** | `git mv` into target layout. Update import-linter rules. | 1 day |
| **P8 — Lock the shape** | Import-linter per layer. Architecture tests. Update `docs/architecture.md` + add ADRs 0005+. | 1 day |

**Total:** 3–4 weeks single-developer. If time-boxed, **P1 + P2 + P3 alone deliver ~80% of the value**; P4–P8 are quality-of-life.

Each phase is shippable. No big-bang rewrite.

---

## 11. Roadmap commitments — near-term and horizon

This section splits named commitments into two tiers. **Near-term (N1–N3)** land in or alongside the migration phases below. **Horizon (H1–H4)** are ~6 months out, contingent on the project continuing; the foundation is shaped to make each additive.

### Near-term — 0–3 months

**N1 — Inline PR code review (§2.17).** Lands with P2 (stage handlers) as part of the REVIEW handler's `StageOutcome` + effects shape. `ReviewAdapter.post_inline_comments` added to the Protocol. One new `Effect` variant.

**N2 — Subtask-driven execution (§2.18).** Lands incrementally: Event ADT variant + `TicketState` parent/children fields in P1; `EPIC_ORCHESTRATE` handler + parent-branch strategy in a dedicated phase after P3. Branch strategy change is the heaviest single piece of this — deserves its own ADR.

**N3 — Worktree-isolated local execution (§2.19).** Lands with P2 or immediately after: new `WorktreeGitAdapter` impl, chosen by `CompositionProfile` for local mode. No engine core changes — the Protocol already absorbs this.

**N4 — Security-in-every-stage (§2.20).** Lands incrementally across P2–P3: each stage handler gains an optional security-effect emitter; `security/` shared module added; `RunSecurityScan` / `AssertNoSecrets` effect variants registered. First concrete checks (secrets scan, dep audit) added in IMPLEMENT, expanded outward from there.

**N6 — Standalone stage execution (§2.21a).** Lands with P2 (stage handlers) as an enforced constraint, not a separate feature. Separate CLI entry points (`a2sdlc review`, `a2sdlc spec`, etc.) and standalone effect-interpreter mode land in P4 or immediately after. GitHub Action packaging per-stage is a follow-on pitch, not a migration phase.

**N8 — Two GitHub Apps (worker + reviewer) + credential profiles (§2.24).** Land with P6 (unified composition). Avoids the self-approval workaround for branch protection. Requires consumer repos to install both Apps and provide both App IDs/keys as secrets. Documented as part of onboarding.

**N9 — Attacker model & prompt injection defense (§G1).** 2–3 month horizon. Deliverable: ADR-0006 "Attacker model and trust boundaries" naming trusted vs untrusted parties, defense layers (tool allowlists, delimiter escaping, effect-level gating), and commitments today vs deferred. Until ADR-0006 lands, public-repo deployments are **experimental-use only**; the docs must say so.

**N5 — Backpropagation / adaptive planning (§2.21). RFC-blocked before implementation.** Depends on N2 (subtask execution) being in place. Lands alongside `EPIC_ORCHESTRATE`: drift-signal Event variants, `TicketState.child_outcomes`, `TriggerSpecRefresh` effect. Q2 (effects-as-audit-log) is a prerequisite.

N5 introduces a cybernetic control loop (re-spec triggered by child outcomes, workload rebalancing, remote writes to the tracker). That is a much bigger claim than the other near-term items. **Before implementation, write an RFC covering:** termination guarantees (no runaway re-spec → re-implement → re-spec), idempotency of tracker-side effects (`SplitChildTicket`, `CancelChild`), auditability requirements on the effects log, and drift-detection heuristics. Do not let §2.21 be treated as sufficient spec.

### Horizon — ~6 months, contingent on project continuing

Four moves are already anticipated by the project owner at roughly the 6-month horizon **if the project succeeds**. The foundation is deliberately shaped so each is additive, not disruptive.

### H1 — The Temporal edition (second distribution, not a migration)

Per product vision §9.2, Temporal is **a second distribution** for larger systems — not a replacement for the CI edition. The CI edition continues to exist for users who want stateless-per-event, git-native execution. The Temporal edition adds long-running durable workflows, external state, and mid-stage resume for customers whose runs outgrow CI constraints.

Same engine core (stage handlers, effects, adapters). Different runtime.

**Why this is already informing the design:** Temporal's fundamental split is "workflow code (deterministic, pure) vs activities (I/O boundary, retryable, idempotent)." The `StageHandler` / `Effect` split adopted here is **the same split**. At Temporal-migration time:

- `pipeline.dispatch` becomes a Temporal workflow.
- Each `Effect` interpreter arm becomes a Temporal activity.
- `RunContext` becomes the workflow state — already serializable by design.
- `middleware/` (retry, idempotency) partially dissolves — Temporal provides both natively.
- `checkpointer` (Q2/Q3 below) becomes Temporal's event history — free.

**What to avoid now, so we don't fight Temporal later:**

- No hidden mutable global state in `pipeline.dispatch`. Everything flows through `RunContext`.
- No I/O inside `handler.effects()` or `handler.preconditions()`. Keep them pure — this is already the rule.
- Effects must be serializable (dataclasses / Pydantic). No closures, no callbacks.
- No `asyncio.gather` / concurrent sub-operations inside a stage. Temporal workflows are single-threaded determinism; parallelism is achieved by multiple activities.

**Recommendation:** write ADR-0006 after P3 lands, committing to "handler output shape is Temporal-ready." No code change — just a constraint the lint layer can enforce (effects must be pickleable).

### H2 — External session storage (Claude Agent SDK + TicketState)

Today: Claude session files live on disk at `.a2sdlc/tickets/{key}/`; `TicketState` lives as `state.json` on the ticket branch. Both are ephemeral-to-CI.

At ~6 months, both move to an external system (likely a KV store: Redis / DynamoDB / Postgres JSONB).

**The foundation already isolates this correctly:**

- `lifecycle/state_storage.py` has a `StateStorage` Protocol with one impl (`GitFileStateStorage`). Adding a remote impl is a new file — zero changes elsewhere.
- Claude session storage is *not yet abstracted*. Today, `pipeline/runner.py` passes `session_id` to the SDK and relies on the SDK's default disk persistence. **This needs a `SessionStorage` Protocol added in P2**, alongside `StateStorage`, so migration is symmetric.

**Migration shape (when the time comes):**

```python
# session/session_storage.py
class SessionStorage(Protocol):
    def save(self, session_id: str, session_data: bytes) -> None: ...
    def load(self, session_id: str) -> bytes | None: ...
    def purge(self, session_id: str) -> None: ...

# Today: LocalDiskSessionStorage (SDK default passthrough)
# ~6mo:  RedisSessionStorage / PostgresSessionStorage
```

**Recommendation:** add `SessionStorage` Protocol in P2 (Stage handlers), with a `LocalDiskSessionStorage` default. Cheap now, painful retrofit later.

### H3 — First-party task tracker

At ~6 months, a proprietary tracker may exist alongside GitHub/Jira adapters. Structurally it's "just another WorkAdapter + ReviewAdapter implementation" — the hexagonal layering handles this.

**What may need flexing:**

- A first-party tracker can emit **richer events** than GitHub/Jira (e.g., direct `stage_requested` events instead of label-inferred). The `Event` ADT needs to accept these without forcing them through label-event shape. Already handled by the sum-type design.
- A first-party tracker can store state **alongside the ticket** natively (no need for `state.json` on branch). Already handled by `StateStorage` Protocol.
- A first-party tracker may want **two-way structured communication** (not just markdown comments). The `WorkAdapter.update_progress` shape needs to not hard-code markdown. Partial today — formatting lives in `domain/progress_format.py`. Moving it to `observability/render/` (already planned for P7) makes per-adapter renderers trivially pluggable.

**Recommendation:** no change to this vision. The foundation absorbs a first-party tracker as a new adapter. Revisit the `update_progress` shape when the tracker's write API is designed.

### H4 — Collapse Mode 1 / Mode 2 into declarative composition

The Mode 1 / Mode 2 split exists because of **tracker topology**, not by design:

- **Mode 2 (GH-native):** GitHub has Actions built in — events trigger workflows directly in the target repo. No external runtime needed.
- **Mode 1 (Jira-dispatcher):** Jira has no compute plane — webhooks fire at our dispatcher, which translates them into runner invocations via `workflow_dispatch`.

The engine core is the same; only the *invocation path* differs. Today this difference leaks into the engine via the `DISPATCHER_URL` env branch in `cli/dispatch.py`. That leak is the real dirtiness — not the existence of two modes.

**The vision already fixes this** (§7.5): `CompositionProfile` makes mode selection declarative. After P6:

- `profile.work = "github_issue"` with `profile.input = "github_event_path"` = Mode 2.
- `profile.work = "workflow_input"` with `profile.output += "dispatcher_http"` = Mode 1.
- `profile.work = "local_file"` with `profile.output = ["console"]` = local dev.
- `profile.work = "a2sdlc_native"` (H3) = first-party tracker.

**No more Mode 1 / Mode 2 terminology in engine code after P6.** They become profile names at the CLI layer and disappear from the engine entirely.

---

## 12. Architectural decisions

### 12.1 Closed

| # | Decision | Resolution |
|---|---|---|
| **Q2** | Effects as an audit log | **REVERSED — no JSONL audit log.** Observability comes from MLflow (metrics, traces, artifacts) + CI logs + git history of `state.json`. Effects are transient, consumed by the interpreter and forgotten. Originally proposed for Temporal-foreshadowing, which is also dropped — the motivation collapsed. |
| **Q4** | Agent-provider abstraction | **`StageRunner` Protocol stable from P2; Claude SDK is the shipping impl.** No generalization in this refactor — second impl appears when a concrete need lands. |
| **Q5** | LangGraph / BAML adoption | **Do not adopt.** Handler/effect split covers the same ground without vendor lock-in. |
| **Q10** | Catalog of skills + CLI commands + flows | **Revisit after P3 ships.** Effect and StageHandler must be real code before we decide whether the catalog is natural extraction or premature generalization. |

### 12.2 Still open

**Q1 — Dispatcher as a formal bounded context.** Write ADR-0005 formalizing "engine and dispatcher are two bounded contexts with a fixed wire protocol (`domain_events`)." Guides future service splits and clarifies H4. **Recommendation:** write before P6.

**Q3 — Durability posture given H1.** With the Temporal edition anticipated, durability (P9) is "deferred to that edition, not built in the CI edition." **Recommendation:** don't build checkpointing now. Enforce the constraints that effects are serializable and handlers are pure (lint-enforce in P8) so the Temporal edition slot-fits.

**Q6 — Move `progress_format.py` out of `domain/`?** Needed for per-tracker renderers (GitHub markdown vs Jira ADF vs GitLab markdown vs first-party tracker format). **Recommendation:** move in P7.

**Q7 — `SessionStorage` Protocol in P2?** Adding this alongside `StateStorage` is cheap now and enables H2 (external session storage in the Temporal edition) with zero engine changes. **Recommendation:** yes, include in P2.

**Q8 — Engine self-observability vs pipeline observability.** Who watches the engine itself (dispatcher uptime, MLflow reachability)? Not the same thing as pipeline observability. **Recommendation:** add a runbook per service component; defer real self-observability (alerting) until a real user needs it.

**Q9 — Versioning / upgrade policy.** Users in 100+ repos upgrading the engine need a backwards-compat story for `config.yaml`, `CompositionProfile` schema, and `TicketState` schema. **Recommendation:** adopt semver; commit to "minor versions are drop-in; major versions require a named migration path." Write ADR-0007 after P6.

**Q11 — Attacker model & trust boundaries (G1).** Ticket bodies, PR diffs, review comments are attacker-controlled input. Agent can call `Bash` / `Write` / `Edit` based on them. **Recommendation:** ADR-0006 in the N9 window (2–3 months). Until then, public-repo deployments are experimental. Defense layers on the table: tool allowlists per stage (REVIEW has no `Write`), delimiter escaping of untrusted content, effect-level gating on merge/label operations. Key decision to close in ADR-0006: commit to a concrete attacker model (who is trusted, what is untrusted input, what defenses apply).

**Q12 — Branch protection fallback behavior.** When target repo's branch protection rejects a merge call, engine must fall back to "PR ready, awaiting human merge" — not spin, not pretend success. **Recommendation:** implement as part of N8 (two-app identity), since the Apps work hand-in-hand with branch protection. Adapter-layer concern.

**Q10 — Catalog of capabilities + flows as composition primitive.** Floated by owner 2026-04-22. The idea: the engine exposes both **skills** (AI-level capabilities like "brainstorm," "write-plan," "review-diff") and **CLI commands** (deterministic capabilities like "run-tests," "post-inline-review," "open-draft-pr") in a single **catalog**. A **flow** is a named composition of catalog entries — possibly the shape that stages themselves take at a finer grain.

Open sub-questions if we pursue this:
- How does context propagate between catalog entries (per-flow context object? effect log? named slots)?
- Are flows themselves catalog entries (so flows can invoke flows)? How deep does nesting go before it's a pipeline again?
- How does this relate to the existing `StageHandler` abstraction — are handlers just one class of flow?
- What layers the catalog — per-stage? per-tracker? global?

**Recommendation:** do not design now. Revisit after P3 ships — once `Effect` and `StageHandler` are concrete, we'll have enough running code to see whether the catalog is a natural extraction or a premature generalization. Capture as Q10 so the thought isn't lost; mark "status: exploring" until there's evidence.

---

## 13. QA strategy — earning trust in real CI

Product principle P-06 says: "real-CI-integration grade, not unit-test grade." This section names the layered test strategy that makes that possible, and what we commit to enforce at each layer.

### 13.1 The gap we're closing

The recurring failure mode today is: **tests pass with fake adapters, then break when running on a real repo in real GitHub Actions with real tokens**. The fake-adapter tests give false confidence because they skip:

- Real webhook payload shapes (GitHub's event payloads have quirks fakes don't model).
- Real API rate limits and retry behavior.
- Real timing (debounce windows, concurrent events, CI job queueing).
- Real token semantics (`ghs_` GitHub-App installation tokens vs `ghp_` PAT vs `secrets.GITHUB_TOKEN`).
- Real branch state (empty branches, force-pushed branches, orphan commits).
- Real concurrency (two CI jobs starting on the same ticket at nearly the same moment).
- Real platform inconsistencies (eventual consistency on label events, label-comment-label ordering).

Closing this gap is what separates "works for the author" from "installed in 100 repos."

**Concrete pattern we've already hit twice:** token-auth surface bugs. The `ghs_` prefix sniff and the `get_app()` probe both passed unit tests and both failed first live smoke. Unit tests can't catch these because the bug lives in the shape of a real API response to a real token type — nothing pure-Python can synthesize. A recorded HTTP-response fixture (pytest-vcr cassette, cost: minutes to capture) would have caught both for the price of one real API call.

**Named classes of bugs unit tests cannot catch** — and which QA layers must handle:

| Bug class | Why units miss it | Layer that catches |
|---|---|---|
| Token-auth surface (prefix sniff, scope probe, 401/403 semantics) | Depends on real API response shape per token type | L4 + recorded cassettes |
| Webhook payload quirks (missing fields, platform-specific shapes) | Fake payloads are too clean | L5 event-replay corpus |
| Rate-limit / retry-after honoring | Timing-dependent; no real `X-RateLimit` header in unit land | L4 + chaos injection at L3 |
| Concurrent event handling | Requires actual parallel invocations | L3 concurrency tests |
| Comment debounce / update ordering | Timing-dependent; fakes collapse time | L4 with real platform clocks |
| Label state ordering (set → remove → set) | Platforms don't always linearize | L4 + eventually-consistent assertions |
| Empty-diff / empty-branch edge cases | Fakes allow what real APIs reject | L4 fixture repos in known states |

### 13.2 The seven test layers

Every release must pass all seven, in order:

| Layer | What it tests | Where it runs | How often |
|---|---|---|---|
| **L1 — Unit** | Pure functions in `domain/`, `ingress/`, `gating/`, effects-interpreter arms in isolation. | `make test` local + every push | Every commit |
| **L2 — Contract** | Each `WorkAdapter` / `ReviewAdapter` / `GitAdapter` impl conforms to Protocol. Fake adapters conform identically. | `make test` every push | Every commit |
| **L3 — Integration with fakes** | Full dispatch flow with fake adapters. Exercises stage handlers, effects, middleware together. | `make test` every push | Every commit |
| **L4 — Real-platform adapter tests** | Each concrete adapter hits the real platform (GH, GL, Jira sandbox) against a dedicated fixture repo / project. | Scheduled CI (nightly) | Nightly + before release |
| **L5 — Event replay** | Real captured webhook payloads (anonymized) replayed through `parse_event` and full dispatch. Regression-tests parsing changes. | `make test` or scheduled | Every push (if fixtures cached) |
| **L6 — End-to-end smoke on real CI** | Full ticket-to-PR-merge cycle running in actual GitHub Actions on a fixture repo. Uses real Claude, real tokens, real MLflow. | Dedicated smoke workflow | Every release + nightly |
| **L7 — Eval harness** | Prompt / stage-runner changes replayed against fixture tickets. Regression detection on metrics. | `make eval` + CI gate | Every PR touching prompts or runners |

### 13.3 Specific practices

**Contract conformance.** Fake adapters and real adapters share a conformance test suite. If the fake passes a test the real fails (or vice versa), the fake is wrong — fix it, don't skip. This closes the "fakes drifted from reality" failure mode.

**Event-replay corpus.** We maintain `tests/fixtures/events/` with anonymized real webhook payloads — one per tracker × per event type × per known edge case. Every parse-event change runs against the corpus. When a real bug is found, the triggering payload is added to the corpus before the fix ships.

**Fixture repos, not mocks, for L4 + L6.** Each tracker adapter gets one dedicated fixture repo (`a2sdlc-fixtures/gh`, `/gl`, `/jira-sandbox`). Real tokens scoped to those repos only. Nightly runs exercise the adapter against real APIs. Cost: real API calls × one run/night — acceptable.

**Chaos injection at L3.** Fake adapters can be configured to: (a) fail N% of calls with a retryable error; (b) fail a specific call once; (c) return stale data; (d) delay responses. Chaos tests assert the pipeline degrades gracefully (blocked state with reason, not corruption).

**Concurrency tests at L3.** Simulate two dispatch invocations against the same ticket starting at the same moment. Assert idempotency middleware catches the dupe; assert state doesn't interleave-corrupt.

**Token-matrix tests at L4 with recorded cassettes.** Each token type (`secrets.GITHUB_TOKEN`, `ghs_` App installation token, `ghp_` PAT, GitLab PAT, GitLab project token) runs against the same test. Permission boundaries surface as test failures, not as surprise production errors.

We use **pytest-vcr** (or equivalent HTTP-recorder) to capture real API responses **once**, then replay them in CI for cheap, deterministic tests. Cassettes are:
- Checked into `tests/cassettes/<token_type>/<operation>.yaml`.
- Regenerated against the real platform quarterly, and whenever an auth-related code path changes.
- Anonymized at capture time (scrub real tokens, real usernames, real repo IDs).
- Committed as the auth-surface regression fence.

**This is the direct answer to the "silly issues in real CI" pain.** Every time a token-auth surface bug escapes to live smoke, the fix ships with a new cassette, and future regressions catch on L4 for the cost of ~seconds of replay.

**Release gate.** A release is not tagged until the L6 smoke workflow completes green against the fixture repo, using the exact artifact that will ship.

### 13.4 What the QA strategy adds to the migration

QA layers are not a new phase — they are retrofitted against existing phases:

| Migration phase | QA layer requirement |
|---|---|
| P1 (domain models) | L1 unit tests for new ADTs; contract tests for TicketState schema versioning. |
| P2 (stage handlers) | L2 contract tests that every handler's `preconditions`, `execute`, `effects` are callable standalone (per §2.21a). |
| P3 (effects + interpreter) | L1 tests per effect arm; L3 integration assertions on effect ordering. |
| P4 (pipe-and-filter) | L3 tests that guard functions short-circuit correctly. |
| P5 (middleware) | L3 chaos tests — idempotency, retry, telemetry behavior under failure. |
| P6 (unified composition) | L4 real-platform tests per profile. Solidify fixture repos per tracker. |
| P7 (rename) | No new tests — all existing tests still pass. |
| P8 (lock the shape) | L6 smoke workflow added to release gate. Import-linter covers invariants. |

### 13.5 Near-term commitment — N7

**N7 — Robust QA strategy in place before v1.** Lands incrementally with P1–P8. Concretely, we commit to:
- L5 event-replay corpus scaffolded in P1.
- L2 contract conformance suite formalized in P2.
- L4 real-platform nightly CI workflow added between P6 and P7.
- L6 smoke workflow as a release gate from P8 onward.
- L7 eval harness scaffold aligned with the existing MLflow integration — pilot in P3 (one stage, one prompt), full coverage post-P8.

Without N7, P-06 is aspirational. With N7, P-06 is enforced.

---

## 14. Non-goals — architectural scope fence

This vision explicitly does **not** propose any of the following, and any attempt to add them without first updating product vision §9 should be rejected:

### Out of scope — deferred to the Temporal edition (§H1)
- Temporal SDK adoption in the engine core.
- Mid-stage durability / checkpointing.
- Long-running workflow state (multi-day, multi-week).
- External session storage or external state storage as the default.

### Out of scope — deferred to a later product phase
- A managed SaaS runtime.
- Multi-tenant identity, tenant isolation, RBAC.
- Web UI / admin dashboard / hosted control plane.
- SSO / SCIM / enterprise identity integration.
- Billing, usage metering, per-seat licensing.
- SOC2 / ISO 27001 / enterprise procurement posture.

### Out of scope — categorically
- Full DDD rewrite with aggregates and repositories (see ADR-0001).
- Event-sourcing or CQRS layer (no separate read path).
- LangGraph / BAML / other agent-framework SDKs as engine dependencies (Q5 closed negative).
- Vertical-slice feature folders (stages are pipeline variants, not independent features).
- Actor-model runtime (CI concurrency group already provides per-ticket isolation).

### Currently in scope (for clarity)
- One engine codebase, **two editions** — CI edition now, Temporal edition at H1.
- All four trackers (GitHub Issues, GitLab Issues, Jira, local file) via adapters.
- Both code hosts (GitHub, GitLab) via adapters.
- Stages runnable standalone (§2.21a) — per-stage CLI entry points and GitHub Action packaging.
- Epic orchestration with hierarchical branches (N2).
- Security-in-every-stage (N4).
- Backpropagation (N5, RFC-blocked).

---

## 15. Relationship to existing documents

- **`docs/architecture.md`** — describes the current shape and rules. Remains authoritative during migration. After P8, sections that describe package layout and composition-root rules are superseded by this vision; the naming rule, domain-purity rule, and extraction rule remain unchanged.
- **ADR-0001 (hexagonal-lite over DDD)** — this vision reaffirms the decision. Hexagonal-lite is the layering; the vision only reshapes composition *within* that layering.
- **ADR-0003 (evaluation not telemetry)** — preserved. `observability/` (live run tracking) and `evaluation/` (judgment / A-B / replay) remain distinct packages.
- **ADR-0004 (import-linter enforcement)** — extended in P8 to cover the new package boundaries (`domain` → `adapters` → `ingress | gating | session | agent | effects | middleware | observability | evaluation | config` → `stages` → `pipeline`).
- **Dispatch-redesign (2026-04-05)** — its label-chain execution model stays. This vision refines the internal shape of the engine, not the CI-orchestration contract.
- **Architecture-v2 (2026-04-12)** — the adapter split (Work / Review / Git), comment lifecycle, follow-up prompt pattern, directive syntax, and state management remain as specified. This vision adds the stage-handler + effects layer on top.

---

## 16. TL;DR

**Five patterns** combined on top of hexagonal-lite:

1. **Pipe-and-filter** composition root.
2. **Strategy** for stages — each `StageHandler` runnable in-pipeline OR standalone (Copilot-reviewer alternative).
3. **Effects-as-data + interpreter** (Redux/Elm-style), persisted as audit log from day one.
4. **Middleware onion** for cross-cutting concerns.
5. **Functional core, imperative shell** discipline — Temporal-ready (H1) at zero cost.

**Twelve bounded-context packages**, named honestly. **Three load-bearing types**: `Event` (sum), `StageHandler` (strategy), `Effect` (sum + interpreter). **One composition root**, declaratively profiled via `CompositionProfile` — killing Mode 1/Mode 2 branching. Engine ships as **two editions** (CI now, Temporal at H1) sharing the same core.

**Seven QA layers** enforce "real-CI-integration grade, not unit-test grade" (product principle P-06) — fake-adapter tests give velocity, real-platform smoke tests give trust.

**3–4 weeks phased migration**, each phase shippable. **Seven near-term commitments** (N1 inline PR review, N2 subtasks, N3 worktrees, N4 security-every-stage, N5 backpropagation RFC-blocked, N6 standalone stages, N7 QA strategy). Four horizon commitments (H1 Temporal edition, H2 external session storage, H3 first-party tracker, H4 mode collapse).

Scales through all ten growth vectors — trackers, stages, events, sinks, gates, providers, modes, eval, concurrency, durability — without structural change.
