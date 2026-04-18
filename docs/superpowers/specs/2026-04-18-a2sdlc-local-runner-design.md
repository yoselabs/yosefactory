# a2sdlc Local Runner — Design

**Date:** 2026-04-18
**Status:** Draft, pending user review
**Revision:** 4 (2026-04-18, post signature-verification review)

## Problem

Today a2sdlc runs inside GitHub CI. Iterating on stage prompts, skill configs, or adapter logic requires pushing a branch and waiting on CI. The feedback loop is too slow for prompt engineering, skill tuning, and informal eval work.

We need to run each pipeline stage locally from iTerm against any repo, capture cost/token/duration metrics per stage, and view them in MLflow — without touching the engine's core code path.

## Goals

1. **Primary:** Run any a2sdlc stage locally, from the terminal, against a target repo, using only offline adapters. No Jira, no GitHub, no CI round-trip.
2. **Handover works across invocations.** Running SPEC then IMPLEMENT in two separate commands produces the same behavior as the CI chain (IMPLEMENT reads SPEC's handover, state, and PR context).
3. **Secondary:** Every local stage run is automatically an eval datapoint — metrics flow to a local MLflow store.
4. **Invariant:** The engine (`pipeline/*`, `stages/*`, `domain/*`, `lifecycle/*`, `assembly/*`, `config.py`) is unchanged. The only variance is which adapter implementations are wired in.

## Non-Goals (v1)

- **A multi-stage orchestrator** (`a2sdlc run` that loops through SPEC→IMPLEMENT→REVIEW→MERGE in one process). The engine is single-stage per `dispatch()` call and we don't introduce a new orchestrator in v1. Locally you run each stage as a separate command.
- Pre-spec / task manifest decomposition (Taskmaster, PRD → tasks).
- Per-stage LLM-as-judge quality scoring.
- Interactive SPEC questions via terminal or answer-file adapters.
- Parallel A/B runs on the same repo. Reintroducible later via a worktree adapter.
- Shared MLflow server. Local file store only.
- Cleanup / prune subcommands.

## Approach

Single engine, per-stage CLI invocations, adapter-selected implementations.

- Each local invocation = one `dispatch()` call with a caller-supplied `trigger_stage` or `is_feedback` flag.
- Local adapters persist engine-required state (ticket body, handover, PR mock, TicketState, feedback) as files under `.a2sdlc/` on the session branch.
- Handover propagation matches existing CI semantics: **the agent reads prior-stage handover files from disk via its Read tool**, because stage prompts in `src/a2sdlc/prompts/stages/*.md` instruct it to do so. The engine does not pipe handover content into `user_prompt` on a normal `trigger_stage=<name>` event (see `dispatch.py:232-233`). This is how CI already works, and local mode changes nothing about it.
- The `is_feedback=True` path (`dispatch.py:76-112`) *does* build a rich context with handover + feedback via `assemble_context` → `user_prompt_override`. Local mode triggers this path only when `.a2sdlc/feedback.json` exists and has not been consumed — i.e., after a REVIEW with `changes_requested`.

## Invocation

One command per stage:

```
a2sdlc run-stage spec      --session <sid> --ticket <file> <repo_path>
a2sdlc run-stage implement --session <sid> <repo_path>
a2sdlc run-stage review    --session <sid> <repo_path>
a2sdlc run-stage merge     --session <sid> <repo_path>
```

- If `--session` is omitted and the current branch matches `a2sdlc/<sid>`, the runner infers `sid` from the branch name.
- If `--session` is omitted on a SPEC invocation (no existing branch), a new ULID is generated and echoed to the user.
- `--ticket` is required on SPEC only; later stages read the ticket from `.a2sdlc/ticket.md` that SPEC persisted.

## Session, Branch, and Ticket Key

- A **session** is a single experiment from SPEC through MERGE. It has one `session_id` (ULID).
- The **branch** is `a2sdlc/<session_id>` in the target repo. Created on SPEC, reused by subsequent stages.
- **`ticket_key = session_id`.** Satisfies the engine's session-id hashing (`config.get_session_id(ticket_key, stage)`) and gives each experiment a unique identity.
- Base branch = current HEAD at SPEC invocation time. Captured and stored in `.a2sdlc/state.json`.
- Re-running the same stage (for eval iteration) is allowed. The CLI does not pass a `run_id`, so `DispatchContext.run_id=None` and the idempotency check at `dispatch.py:146` is skipped. Note: the engine's SDK session ID is deterministic per `(ticket_key, stage)` (see `runner.py:53`), so a re-run within the same session may resume the prior SDK session. This is benign — the agent gets a warm context. If you need a fully fresh run, start a new session.

## Configuration

`.a2sdlc/config.yaml` lives in the target repo and is authoritative for both local and CI runs. **This replaces the existing `a2sdlc.yaml` path** — migrating the config location is an accepted engine-adjacent change (it touches `config.py` only).

```yaml
adapters:
  work:     local_file       # alt: jira
  review:   local_noop       # alt: github
  git:      local_branch     # alt: github
  progress: console          # alt: gh_actions

stages: [spec, implement, review, merge]   # security off by default

spec:
  mode: auto                 # v1: only mode

quality:
  check_command: "make check"

model: claude-sonnet-4-6
```

**Fallback rules:**
- If `.a2sdlc/config.yaml` is missing: CLI exits with a clear error pointing to a template path.
- CLI flags override any config key.
- Unknown keys are a hard error. (Requires updating `config.load_config_file`, which is currently lenient — called out as an engine change below.)
- Config is snapshotted into `.a2sdlc/runs/<session_id>/run-<stage>.json` at invocation start.

## State Layout — On The Branch

All engine state and handover artifacts live in `.a2sdlc/` on the session branch. This matches CI semantics: the existing `LocalGitAdapter.write_state` already writes `.a2sdlc/state.json` to the branch. Local mode simply adds more files to the same folder via the local work and review adapters.

```
<target_repo>/
├── .a2sdlc/
│   ├── state.json                      # TicketState (unchanged — same file CI writes)
│   ├── ticket.md                       # persisted ticket body (so later stages find it)
│   ├── handover/
│   │   ├── spec.md                     # what finalize_comment would write to Jira
│   │   ├── implement.md
│   │   └── review.md
│   ├── pr.json                         # mock PR state (pr_number, approvals, status, reviews)
│   ├── feedback.json                   # REVIEW output feeding next IMPLEMENT invocation
│   └── runs/<session_id>/
│       ├── spec.json                   # runner-level stage dump (cost, tokens, turns)
│       ├── implement.json
│       ├── review.json
│       ├── merge.json
│       ├── run-<stage>.json            # config snapshot + invocation metadata
│       └── logs/<stage>.log            # captured rich output
└── ... user code ...
```

**What stays outside the repo**

Only MLflow. `~/.a2sdlc/mlflow` is a global file-store backend shared across all repos and sessions. Everything else lives on the branch.

## Ports and Adapter Surface

Current `adapters/` layout is flat: `work.py`, `review.py`, `git.py`, `github.py`, `retry.py`, `protocols.py`. New adapters use the same flat naming.

### Existing ports (in `adapters/protocols.py`, unchanged)

- `GitAdapter` — `setup_branch`, `sync_with_base`, `commit_artifacts`, `push`, `read_state`, `write_state`.
- `WorkAdapter` — full surface (14 methods): `parse_event`, `format_branch`, `set_stage_label`, `set_blocked`, `set_done_label`, `begin_comment`, `finalize_comment`, `collect_issue_feedback`, `find_last_handover`, and related ticket read/write ops. (If the current `WorkAdapter` protocol is narrower, it gets widened to match what `dispatch.py` actually calls; this is an engine-adjacent change to `protocols.py` only.)
- `ReviewAdapter` — full surface (~10 methods): `create_draft_pr`, `post_review`, `get_approvals`, `read_context`, `check_human_approval`, `mark_pr_ready`, `merge_pr`, `collect_pr_feedback`, and related.
- `StageRunner` — Claude Agent SDK wrapper; no change.

### New ports

- **`ProgressAdapter`** — receives structured progress events from the engine and renders them. Used by two implementations below.

No other new ports in v1. The "local ticket source" concept piggybacks on `WorkAdapter` (see below); no separate `TicketAdapter`.

### New adapter files (flat layout)

- `adapters/local_file_work.py` — **full `WorkAdapter` implementation.** Reads the ticket from the CLI-supplied markdown file on first invocation, persists it to `.a2sdlc/ticket.md`, and provides all 14 `WorkAdapter` methods. Behaviors summarized below.
- `adapters/local_noop_review.py` — **full `ReviewAdapter` implementation.** PR state is file-backed in `.a2sdlc/pr.json`. Behaviors summarized below.
- `adapters/local_branch_git.py` — `git checkout -b a2sdlc/<session_id>`, stage commits, no push. `read_state` / `write_state` delegate to the existing `LocalGitAdapter` behavior (`.a2sdlc/state.json` on branch — no override needed).
- `adapters/progress_console.py` — `rich`-based live console renderer (see "Live Console UX").
- `adapters/progress_gh_actions.py` — `::group::` renderer extracted from current `evaluation/progress.py` and `runner.py`.

### Unchanged adapter files

`adapters/git.py`, `adapters/github.py`, `adapters/work.py`, `adapters/review.py`, `adapters/retry.py`.

### Engine-adjacent files touched (small, explicit)

- `adapters/protocols.py` — add `ProgressAdapter` port. Widen `WorkAdapter` / `ReviewAdapter` only if current protocols under-specify methods `dispatch.py` already calls.
- `config.py` — rename config path to `.a2sdlc/config.yaml`, fail on unknown keys, load the `adapters:` block.
- `evaluation/progress.py`, `pipeline/runner.py` — extract the `::group::` / `rich.log` rendering into the `progress` adapters. Pure refactor; behavior preserved.
- `cli.py` — add `run-stage` subcommand.

## Adapter Behaviors (Local)

### `local_file_work` (`WorkAdapter`)

Signatures match the protocol in `adapters/work.py` exactly (12 methods). Behavior:

- `parse_event()` → `PipelineEvent(key=session_id, trigger_stage=<CLI arg or None>, is_feedback=<bool>, pr_number=<from pr.json or None>)`.
  - On `run-stage spec`: `trigger_stage=SPEC, is_feedback=False`.
  - On `run-stage implement/review/merge`: `trigger_stage=<stage>, is_feedback=False` — UNLESS `.a2sdlc/feedback.json` exists with `consumed=false`, in which case `trigger_stage=None, is_feedback=True` (routes through the feedback path where handover + feedback are assembled into the user prompt).
- `get_ticket(key)` → reads `.a2sdlc/ticket.md`.
- `get_labels(key)` → returns `[]` (labels have no meaning locally).
- `begin_comment(key)` → returns a new comment id (e.g. `f"{key}-{stage}-{cycle}"`), initializes an in-memory buffer. The runner tracks the active stage name externally so `finalize_comment` knows which handover file to write.
- `update_progress(comment_id, body)` → appends to the in-memory buffer (optional; can be a no-op locally since progress goes to `rich.Live`).
- `finalize_comment(comment_id, body)` → writes `body` to `.a2sdlc/handover/<stage>.md` where `<stage>` is looked up from the runner's active-stage map keyed by `comment_id`.
- `set_stage_label(key, stage)` / `set_blocked(key, reason)` / `set_done_label(key)` — no-ops, logged at INFO.
- `format_branch(ticket_key)` → `f"a2sdlc/{ticket_key}"`.
- `collect_issue_feedback(key, since)` → returns `[]` (no issue-side feedback locally in v1).
- `find_last_handover(key)` → reads `.a2sdlc/handover/*.md` and returns the most recent as a `HandoverComment` with a synthetic `created_at` derived from file mtime and `stage` parsed from the filename stem. Returns `None` if none exist.

### `local_noop_review` (`ReviewAdapter`)

Signatures match the protocol in `adapters/review.py` exactly (10 methods). Behavior:

- State backing: `.a2sdlc/pr.json`:
  ```json
  {
    "pr_number": 1,
    "status": "draft",
    "title": "...",
    "body": "...",
    "reviews": [
      {"cycle": 1, "verdict": "changes_requested", "body": "...", "created_at": "..."}
    ]
  }
  ```
- `create_draft_pr(branch, base, title, ticket_key)` → writes initial `pr.json`, returns `pr_number=1`. Synthetic but stable within a session.
- `update_pr(pr_number, title, body, ticket_key)` → updates `pr.json`.
- `mark_pr_ready(pr_number)` / `merge_pr(pr_number, method)` → updates `status` field; no network.
- `get_approvals(pr_number)` → returns `[Approval(user="local", is_bot=False)]`. This satisfies `check_human_approval` at `lifecycle/pr.py:31-34` which checks `any(not a.is_bot for a in approvals)`.
- `post_review(pr_number, body, verdict)` → appends to `reviews[]`. If `verdict == "changes_requested"`, also writes `.a2sdlc/feedback.json` with `{consumed: false, body, cycle, created_at}` (ISO timestamp).
- `read_pr_diff(pr_number)` → returns `git diff <base>..HEAD` output on the session branch.
- `read_pr_comments(pr_number)` → returns `reviews[]` mapped to `ReviewComment`.
- `collect_pr_feedback(pr_number, since)` → reads `.a2sdlc/feedback.json`. Returns `[]` if missing, `consumed=true`, or `created_at <= since`. Otherwise returns one `FeedbackItem`. Does NOT mark consumed — see Feedback Consumption Ordering below.
- `find_last_handover(pr_number)` → returns `None` (no PR-side handover concept locally; all handover lives on the issue side via `WorkAdapter.find_last_handover`).

### Feedback Consumption Ordering

To avoid losing feedback on stage crash, the runner (not the adapter) is responsible for flipping `consumed=true` in `.a2sdlc/feedback.json` **after** a successful dispatch return (`DispatchResult` without `blocked=True` and without `error`). The adapter's `collect_pr_feedback` is read-only. This means:

- Stage reads feedback, crashes → `consumed=false` persists, next invocation re-reads the same feedback. Safe.
- Stage reads feedback, succeeds → runner marks `consumed=true` post-dispatch. Subsequent runs won't re-consume.

### `local_branch_git` (`GitAdapter`)

The existing `LocalGitAdapter` in `adapters/git.py` does `git fetch origin; git merge origin/<base>` in `setup_branch` and `sync_with_base`. This fails locally when there is no `origin` remote (or the remote is unreachable). The local adapter **overrides `setup_branch` and `sync_with_base`** to skip remote interactions:

- `setup_branch(branch, base)`:
  - If branch does not exist: `git checkout -b <branch> <base>` (pure-local, no fetch).
  - If branch exists: `git checkout <branch>`.
  - Dirty-tree check: if the working tree has conflicting changes, raise `BlockedError` with a clear message. If non-conflicting, carry changes over and WARN.
- `sync_with_base(base)` — no-op locally. Returns True. MERGE's pre-merge sync becomes a no-op, which is consistent with "no actual merge to base" in local mode.
- `commit_artifacts(message, paths)` — same as existing.
- `push()` — no-op.
- `read_state()` / `write_state()` — inherit the existing file-on-branch behavior (`.a2sdlc/state.json`). No override.

## Per-Stage Flow

### `run-stage spec`

1. Session id resolved (from `--session`, or generated).
2. Ticket file copied to `.a2sdlc/ticket.md` after `setup_branch` creates the branch.
3. `parse_event` returns `PipelineEvent(key=sid, trigger_stage=SPEC, is_feedback=False, pr_number=None)`.
4. `dispatch.py:177` sees SPEC + `pr_number=None`, calls `create_draft_pr` → writes `.a2sdlc/pr.json` with `pr_number=1`.
5. `user_prompt = clean_body` (ticket text). System prompt loaded via `assemble_system_prompt` — includes the SPEC stage prompt which instructs the agent.
6. SPEC stage runs in auto-mode (system prompt gains the "do not ask questions" prefix at `dispatch.py:223-227`).
7. `finalize_comment` writes `.a2sdlc/handover/spec.md`.
8. Stage result persisted; `state.json` updated; MLflow child run logged.

### `run-stage implement`

1. Session id resolved; `setup_branch` checks out `a2sdlc/<sid>`.
2. `parse_event` checks for `.a2sdlc/feedback.json`:
   - **If missing or consumed:** `PipelineEvent(trigger_stage=IMPLEMENT, is_feedback=False, pr_number=1)`. Routes through `dispatch.py:126` → `target_stage=IMPLEMENT`. `user_prompt = clean_body` (ticket only). The agent's stage prompt instructs it to read `.a2sdlc/handover/spec.md` to pick up the spec — matching how CI already works.
   - **If present and unconsumed:** `PipelineEvent(trigger_stage=None, is_feedback=True, pr_number=1)`. Routes through `dispatch.py:76-112`. `assemble_context` builds a user prompt with ticket + handover + feedback. `target_stage = resolve_target_stage(...)`.
3. IMPLEMENT stage runs, writes code, `finalize_comment` → `.a2sdlc/handover/implement.md`.
4. If feedback was consumed in this run: runner flips `consumed=true` in `.a2sdlc/feedback.json` **after** successful dispatch return.
5. Quality Gate runs (see section).
6. MLflow child run logged.

### `run-stage review`

Analogous to IMPLEMENT (first-run path). The REVIEW stage produces a verdict; the stage prompt instructs the agent to call an output format that the engine parses. `post_review` is called with that verdict — on `changes_requested`, feedback.json is written.

### `run-stage merge`

1. `parse_event` returns `PipelineEvent(trigger_stage=MERGE, is_feedback=False, pr_number=1)`.
2. `dispatch.py:189-208` branch. `pr_number=1` (from pr.json). Gate is HUMAN by default.
3. `check_human_approval` calls `get_approvals(1)` → `[Approval("local", is_bot=False)]` → passes.
4. `sync_with_base` is a no-op locally.
5. `merge_pr` updates `pr.json.status = "merged"`.
6. `set_done_label` is a no-op.
7. MLflow child run logged.

## SPEC in Auto Mode

- `spec.mode: auto` is the only supported value in v1.
- The stage's question-asking code path is gated off when `mode=auto`.
- No question adapter is required in v1.

## Stage Toggles

- `stages` list in config is the allowlist.
- `--stages` CLI flag on `run-stage` is not supported — you invoke one stage at a time.
- Security stage is implemented but omitted from the default list. In local mode it runs the same stage logic as CI; no local-specific adapter is needed. Enabling it locally requires whatever tooling the stage's prompt expects to be present (e.g., `bandit`).

## Directives

Directives (`[a2sdlc base=...]`, etc.) parsed by `domain/directives.py` from the ticket body are honored locally. **Directives win over runner-captured defaults:** `[a2sdlc base=main]` in the ticket overrides the captured HEAD as the base branch. This matches CI behavior.

## MLflow Telemetry

- On by default for local stage runs; disabled via `--no-track`.
- Backend: local file store at `~/.a2sdlc/mlflow`.
- Experiment name: the target repo's basename.
- **Run hierarchy:** one MLflow parent run per session (`session_id`), one child run per stage invocation. Re-running a stage adds another child run under the same parent.
- Per-stage metrics: `tokens_in`, `tokens_out`, `turns`, `cost_usd`, `duration_sec`, `model`, `outcome`.
- Session-level rollup (computed on each child run, overwritten on the parent): `total_cost_usd`, `total_tokens_*`, `total_duration_sec`, `stages_executed`.
- Tags: `session_id`, `stage`, `model`, `git_sha_before`, `git_sha_after`, `dirty_tree_before`, `cycle` (for re-runs).
- MLflow availability: if the backend is unreachable and `--no-track` was not passed, the CLI exits with an error before any stage runs.

## Quality Gate

- **When it runs:** at the end of `run-stage implement` only. Running `make check` after SPEC or REVIEW alone makes no sense.
- **Where it runs:** in the target repo working tree, on the `a2sdlc/<sid>` branch.
- **What it does:** shells out to `quality.check_command`, captures stdout/stderr as an MLflow artifact, logs exit code as `quality_passed` (1 if exit 0, else 0).
- **Blocking:** observational only in v1. Does not prevent later `run-stage review` from executing.
- **CLI exit code:** `run-stage implement` exits non-zero if `quality_passed=0`.

## Live Console UX

- `adapters/progress_console.py` uses `rich.Live` + `rich.Layout`:
  - **Top pane (scrolling):** stage events — tool calls, outputs — throttled to the engine's existing 5s SDK streaming cadence.
  - **Bottom pane (persistent status bar):** `stage: <name> | tokens: <in>/<out> | cost: $<usd> | turns: <n> | elapsed: <mm:ss> | session: <sid>`.
- Refresh on every stage event plus a 1Hz tick for smooth elapsed time.
- GitHub Actions uses `progress_gh_actions.py` instead. The engine sees the same `ProgressAdapter` port.

## Post-Run Output

After `run-stage <name>` completes:

```
✓ Stage <name> done   quality: <PASS|FAIL|N/A>   cost: $<x.xx>   elapsed: <mm:ss>
  Session:  <session_id>
  Branch:   a2sdlc/<session_id>
  MLflow:   mlflow ui --backend-store-uri ~/.a2sdlc/mlflow
  State:    <repo>/.a2sdlc/
  Next:     a2sdlc run-stage <next_stage> --session <session_id> <repo>
```

User is left on the session branch.

## Failure Modes

- **Crash mid-stage:** runner-level stage state (`.a2sdlc/runs/<sid>/<stage>.json`) is written atomically on stage completion only. A partially-executed stage leaves no child file; re-running `run-stage <stage>` starts fresh.
- **Ctrl-C:** runner marks the active MLflow child run as `KILLED`, does not write runner-level stage state. The engine may have partially updated `.a2sdlc/state.json` via `write_state` before the signal — re-running the stage will see that state and proceed.
- **MLflow unreachable:** CLI exits with error before any stage runs (unless `--no-track`).
- **Branch mismatch on non-SPEC stage:** if branch `a2sdlc/<sid>` does not exist, CLI exits with a clear error.
- **User on a different branch:** `setup_branch` unconditionally checks out the session branch. If the user's current branch has uncommitted changes that would conflict, the checkout fails — runner surfaces the git error and exits. If changes don't conflict, they carry over silently (git's default behavior).
- **Dirty tree at any stage:** runner emits WARN, tags MLflow with `dirty_tree_before: true`. No auto-stash.
- **Feedback not consumed due to stage crash:** feedback.json's `consumed=false` persists, next invocation re-reads. Safe by design (see Feedback Consumption Ordering).
- **Circuit breaker on REVIEW:** `dispatch.py:151-161` blocks REVIEW after `max_review_cycles` (default 2, see `config.py`). To reset, edit `.a2sdlc/state.json` to zero `review_cycles` or start a new session.

## Resume

"Resume" locally = "run the stage again."

- Re-running `run-stage <name> --session <sid>` in an existing session re-executes the stage against the current `.a2sdlc/` state on the branch. Prior runner-level stage JSON (`.a2sdlc/runs/<sid>/<stage>.json`) is overwritten — for eval-datapoint preservation, rely on MLflow (each invocation is a new child run).
- The engine's SDK session ID is deterministic from `(ticket_key, stage)` via `config.get_session_id` (see `runner.py:53`), so the SDK may resume the prior session from its side. This is benign; the agent gets a warm context. If you need a cold start, begin a new session.
- MLflow logs each invocation as a new child run under the same parent. The child run's `cycle` tag increments from the count of prior child runs for that `(session, stage)`.
- No separate `--resume` or `--from` flag. The CLI is uniform.
- **Note on `review_cycles`:** `runner.py:53` currently calls `get_session_id(ticket_key, stage)` without passing `review_cycles`, even though `config.get_session_id` accepts it. This means the SDK session ID does not differentiate on cycle count. Consistent with the "re-run may resume prior SDK session" behavior above. Threading `review_cycles` through is future work, not a v1 change.

## What Stays Untouched

- `pipeline/dispatch.py`, `pipeline/stage_executor.py`, `pipeline/runner.py` (except the progress-rendering refactor), `pipeline/feedback_routing.py`, `pipeline/context_assembly.py`
- `stages/*.py`
- `domain/*`
- `lifecycle/*`
- `assembly/*`
- `evaluation/stats.py`

## Known Limitations

- **Single-user, single-machine.** MLflow experiment name is the target repo basename; two different repos with the same basename collapse into one experiment. Acceptable for v1.
- **Per-stage model override not supported.** Config has a single top-level `model:`. Future-shape (`stages.implement.model`) is out of scope.
- **Gates default to HUMAN in code** (`domain/models.py`). The `local_noop_review` returns a synthetic approval so MERGE does not block. If you want to exercise "gate blocks until human approves" behavior locally, that's a future config toggle, not v1.
- **Directive override of base branch** may conflict with the user's intuition (they expect HEAD to be the base). Documented; not fixed.

## Open Questions for Implementation Plan

- MLflow dependency weight — optional extra (`pip install a2sdlc[local]`) or core dep?
- Whether the Jira work adapter needs refactoring to conform to the same `WorkAdapter` protocol the local adapter implements, or whether the protocol is already correctly shaped.
- Config-file migration path from existing `a2sdlc.yaml` to `.a2sdlc/config.yaml` — one-shot rename in this work, or dual-path grace period?

## Future Work (out of this spec)

- `a2sdlc run` multi-stage orchestrator that drives SPEC→IMPLEMENT→REVIEW→MERGE in one invocation (introduces a `pipeline/orchestrator.py` layer above `dispatch`).
- Taskmaster integration: consume `tasks.json` as a `WorkAdapter` source, loop over tasks in dependency order.
- Per-stage LLM judges (DeepEval) for SPEC quality scoring.
- Terminal / answers-file SPEC question adapters.
- Worktree adapter for parallel A/B runs on the same repo.
- `a2sdlc sessions prune` for branch + .a2sdlc cleanup.
- Shared MLflow server (Dokploy-hosted) for cross-machine run comparison.
- `gates.merge=AUTO` in local config to truly exercise the merge path without synthetic approvals.
