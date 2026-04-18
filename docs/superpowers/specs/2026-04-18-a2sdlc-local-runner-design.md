# a2sdlc Local Runner — Design

**Date:** 2026-04-18
**Status:** Draft, pending user review
**Revision:** 3 (2026-04-18, post flow-gap review)

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

- Each local invocation = one `dispatch()` call with a caller-supplied `trigger_stage`.
- Local adapters persist all engine-required state (ticket comments, handover, PR, TicketState, feedback) as files under `.a2sdlc/` on the session branch.
- Handover between stages works because stage N+1's dispatch reads from the same `.a2sdlc/` folder stage N wrote to.
- The engine's existing deterministic `session_id = f(ticket_key, stage, review_cycles)` is correct under this model: same session within a stage's retries, distinct sessions across stages.

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
- **`ticket_key = session_id`.** This satisfies the engine's session-id hashing and idempotency logic and gives each experiment a unique identity.
- Base branch = current HEAD at SPEC invocation time. Captured and stored in `.a2sdlc/state.json`.
- Re-running the same stage (for eval iteration) within a session is allowed; each invocation produces a fresh `run_id` so idempotency does not self-trigger.

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

- `parse_event()` — returns `PipelineEvent(key=session_id, trigger_stage=<CLI arg>, is_feedback=<from feedback.json presence>, pr_number=<from pr.json>)`. `is_feedback` is True on an IMPLEMENT invocation when `.a2sdlc/feedback.json` exists and its `consumed` flag is False.
- `format_branch(key)` → `f"a2sdlc/{key}"`.
- `set_stage_label(stage)` / `set_blocked()` / `set_done_label()` — no-ops locally (no Jira labels to drive workflow triggers). Logged at INFO for visibility.
- `begin_comment(stage)` — creates an in-memory comment buffer.
- `finalize_comment(stage, body)` — writes body to `.a2sdlc/handover/<stage>.md`.
- `find_last_handover(stage=None)` — reads the most recent handover file relevant to the requested stage (or the latest).
- `collect_issue_feedback()` — returns empty locally (no Jira issue comments in v1).

### `local_noop_review` (`ReviewAdapter`)

- State backing: `.a2sdlc/pr.json` schema:
  ```json
  {
    "pr_number": 1,
    "status": "draft" | "ready" | "merged",
    "reviews": [{"stage_cycle": 1, "outcome": "approved" | "changes_requested", "body": "..."}],
    "approvals": ["local"]
  }
  ```
- `create_draft_pr(branch, base, key)` — writes initial pr.json, returns `pr_number=1`. Synthetic but stable within a session.
- `post_review(pr_number, outcome, body)` — appends to `reviews[]`. If `changes_requested`, also writes `.a2sdlc/feedback.json` with `{consumed: false, body: <review body>, cycle: N}`.
- `get_approvals(pr_number)` — in v1 returns a synthetic approval `["local"]` so MERGE's `check_human_approval` passes. (Future: `gates.merge=AUTO` in local config could short-circuit this; left for later.)
- `read_context(pr_number)` — returns content from pr.json + .a2sdlc/handover/.
- `mark_pr_ready(pr_number)` / `merge_pr(pr_number)` — update status in pr.json, no network.
- `collect_pr_feedback()` — reads `.a2sdlc/feedback.json` if present and not yet consumed, returns a feedback event and marks it consumed.

### `local_branch_git` (`GitAdapter`)

- `setup_branch(branch, base)` — on first call for a session: `git checkout -b <branch>` from `base`. On subsequent calls for the same branch: `git checkout <branch>`. Dirty-tree warn + MLflow tag (see below).
- `sync_with_base(base)` — `git merge <base>` into branch. Same as existing LocalGitAdapter.
- `commit_artifacts(message, paths)` — same as existing.
- `push()` — no-op.
- `read_state()` / `write_state()` — delegate to the existing LocalGitAdapter implementation (reads/writes `.a2sdlc/state.json` on the branch). No override needed here.

## Per-Stage Flow

### `run-stage spec`

1. Session id resolved (from `--session`, or generated).
2. `local_branch_git.setup_branch("a2sdlc/<sid>", current HEAD)` — creates branch.
3. `local_file_work` reads `--ticket` path, persists to `.a2sdlc/ticket.md`.
4. Runner calls `dispatch(event=PipelineEvent(key=sid, trigger_stage=SPEC, ...), ctx)`.
5. `dispatch.py` creates draft PR via `local_noop_review.create_draft_pr` → writes `.a2sdlc/pr.json`.
6. SPEC stage runs in auto-mode; output captured; `finalize_comment` writes `.a2sdlc/handover/spec.md`.
7. Stage result persisted to `.a2sdlc/runs/<sid>/spec.json`; state.json updated via `write_state`.
8. MLflow sub-run logged under session's parent MLflow run.

### `run-stage implement`

1. Session id resolved (from branch name or `--session`).
2. `git checkout a2sdlc/<sid>` (no `-b`).
3. `local_file_work.parse_event` returns `PipelineEvent(key=sid, trigger_stage=IMPLEMENT, is_feedback=<feedback.json present and not consumed>, pr_number=1)`.
4. `dispatch.py` loads prior TicketState and handover from `.a2sdlc/`.
5. IMPLEMENT stage runs, writes code, `finalize_comment` → `.a2sdlc/handover/implement.md`.
6. Stage result persisted; Quality Gate runs (see section).

### `run-stage review`

Analogous. `local_noop_review.post_review` writes review outcome to pr.json; on `changes_requested` also writes feedback.json.

### `run-stage merge`

Analogous. `local_noop_review.get_approvals` returns synthetic approval; MERGE completes; pr.json status → merged. No actual git merge to base.

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

- **Crash mid-stage:** stage state is written atomically on stage *completion* only (write to `.a2sdlc/runs/<sid>/<stage>.json.tmp`, `os.rename` to final). A partially-executed stage leaves no child file; re-running `run-stage <stage>` starts fresh.
- **Ctrl-C:** runner marks the active MLflow child run as `KILLED`, does not write runner-level stage state. The engine may have partially updated `.a2sdlc/state.json` via `write_state` before the signal — re-running the stage will see that state and proceed.
- **MLflow unreachable:** CLI exits with error before any stage runs (unless `--no-track`).
- **Branch mismatch on non-SPEC stage:** if the user runs `run-stage implement --session <sid>` and branch `a2sdlc/<sid>` does not exist, CLI exits with a clear error.
- **Dirty working tree on first invocation:** runner emits WARN, tags MLflow with `dirty_tree_before: true`, does not auto-stash. Uncommitted changes carry over with the branch switch.

## Resume

"Resume" locally = "run the stage again."

- Re-running `run-stage spec --session <sid>` in an existing session deletes `.a2sdlc/handover/spec.md` and re-executes SPEC. The engine's SDK-session resume kicks in automatically because `session_id = f(ticket_key=<sid>, stage=SPEC, review_cycles=0)` is deterministic and the SDK session from the prior attempt still exists.
- To force a fully fresh SDK session (new session_id seed), bump the `review_cycles` counter via `--cycle <n>` or just create a new session.
- MLflow logs the retry as a new child run under the same parent with `cycle` tag incremented.
- No separate `--resume` or `--from` flag. The CLI is uniform.

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
