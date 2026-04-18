# a2sdlc Local Runner — Design

**Date:** 2026-04-18
**Status:** Draft, pending user review
**Revision:** 2 (2026-04-18, post-review)

## Problem

Today a2sdlc runs inside GitHub CI. Iterating on stage prompts, skill configs, or adapter logic requires pushing a branch and waiting on CI. The feedback loop is too slow for prompt engineering, skill tuning, and informal eval work.

We need to run the full pipeline (or any subset of stages) locally from iTerm against any repo, capture cost/token/duration metrics, and view them in MLflow — without touching the engine's core code path.

## Goals

1. **Primary:** Run the a2sdlc pipeline locally, from the terminal, against a target repo, using only offline adapters. No Jira, no GitHub, no CI round-trip.
2. **Secondary:** Every local run is automatically an eval datapoint — metrics flow to a local MLflow store.
3. **Invariant:** The engine (`pipeline/dispatch.py`, `stages/*`, `domain/*`, `lifecycle/*`, `assembly/*`) is identical between local and CI runs. The only variance is which adapter implementations are wired in.

## Non-Goals (v1)

- Pre-spec / task manifest decomposition (Taskmaster integration, PRD → tasks).
- Per-stage LLM-as-judge quality scoring.
- Interactive SPEC questions via terminal or answer-file adapters.
- Parallel A/B runs on the same repo. (Reintroducible later via a worktree adapter.)
- Shared MLflow server. Local file store only.
- `runs prune` or any branch-management QOL subcommands.

## Approach

Single CLI, adapter-selected implementations, existing engine unchanged.

- The engine imports ports, not concrete adapters.
- A config file in the target repo (`.a2sdlc/config.yaml`) names which adapter to use per port.
- CLI flags override config keys.
- "Local mode" is not a concept in code — it's simply a config that names the local-side adapters.

## Invocation

```
a2sdlc run <repo_path> --ticket <file>
a2sdlc run <repo_path> --ticket <file> --stages spec,implement
a2sdlc run <repo_path> --resume <run_id> --from implement
```

## Configuration

`.a2sdlc/config.yaml` lives in the target repo and is authoritative for **both** local and CI runs — CI reads the same file since it's committed to the repo. This is the single source of truth; there is no separate CI config.

```yaml
adapters:
  ticket:   local_file       # alt: jira
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
- If `.a2sdlc/config.yaml` is **missing**: CLI exits with a clear error pointing to a template path. No implicit defaults — explicit config is required.
- **CLI flags override** any config key (e.g., `--stages`, `--ticket-adapter`).
- **Unknown keys** are a hard error (no silent typos).
- Config is snapshotted into `run.json` at run start; edits to the config file mid-run do not affect the running pipeline.

## Run Identity and State Layout

Each invocation generates a ULID `run_id`.

```
~/.a2sdlc/runs/<run_id>/
  run.json               # ticket ref, config snapshot, model, start time
  stages/
    spec.json            # StageResult + captured state
    implement.json
    review.json
    merge.json
  logs/
    <stage>.log          # rich console output captured
  mlflow/                # local mlflow store (or shared parent dir)
```

No subdirectory for code. Code lives on a branch in the target repo.

## Git Behavior

- **Base branch:** current `HEAD` at invocation time. Runner captures the sha as `git_sha_before`.
- **Branch creation:** `git checkout -b a2sdlc/<run_id>` from that HEAD. On `--resume`, runner uses `git checkout a2sdlc/<run_id>` (no `-b`) and assumes the branch still exists.
- Stage commits happen on that branch in the target repo working tree.
- **No push.** The `local_branch` adapter implements `GitAdapter.push()` as a no-op (the port already exists in `adapters/protocols.py`).
- On completion, the user is left on the run branch. Switching back is a manual `git checkout`.
- **Dirty-tree handling:** not pre-checked; uncommitted changes carry over with the branch switch. Runner emits a WARN log and tags MLflow with `dirty_tree_before: true` when the tree is dirty, so eval data isn't silently poisoned. No auto-stash, no auto-commit.
- **`git_sha_after`:** captured after the last commit the pipeline produced (or equals `git_sha_before` if no commits were made).
- No prune or cleanup subcommand. Branches accumulate; delete manually.

## Ports and Adapter Surface

The current `adapters/` layout is **flat** (per `docs/architecture.md` §1): `work.py`, `review.py`, `git.py`, `github.py`, `retry.py`, `protocols.py`. New adapters in v1 use the same flat naming — no subfolder migration. Existing files stay put.

### Existing ports (in `adapters/protocols.py`, unchanged)

- `GitAdapter` — `setup_branch`, `sync_with_base`, `commit_artifacts`, `push`, `read_state`, `write_state`.
- `StageRunner` — Claude Agent SDK wrapper; no change.
- (Plus any `WorkAdapter` / `ReviewAdapter` already present.)

### New ports (added to `adapters/protocols.py`)

- **`TicketAdapter`** — produces the ticket domain type from a source. Two implementations: `local_file` (reads markdown from a path) and `jira` (refactor of existing Jira code into the new port if not already shaped this way).
- **`ProgressAdapter`** — receives structured progress events from the engine and renders them. Two implementations: `console` (uses `rich.Live`) and `gh_actions` (existing `::group::` output, refactored out of `evaluation/progress.py`).

`evaluation/progress.py` remains the engine-side progress tracker (cadence, event assembly, 5s throttle). It calls the `ProgressAdapter` to render. This keeps `evaluation/` as progress *logic* and `adapters/` as progress *presentation*, matching the layering rules in `docs/architecture.md` §2.

### New adapter files (flat layout)

- `adapters/ticket_local_file.py`
- `adapters/git_local_branch.py` — implements `GitAdapter.push()` as a no-op.
- `adapters/progress_console.py` — `rich`-based live console renderer (see "Live Console UX").
- `adapters/progress_gh_actions.py` — `::group::` renderer extracted from current `evaluation/progress.py`.

### Unchanged files

`adapters/git.py`, `adapters/github.py`, `adapters/work.py`, `adapters/review.py`, `adapters/retry.py`.

## SPEC in Auto Mode

- `spec.mode: auto` is the only supported value in v1.
- The stage's question-asking code path is gated off when `mode=auto`.
- No question adapter is required in v1.
- Rationale: clarifying questions should be absorbed by a future pre-spec step (done outside a2sdlc). If SPEC asks questions in auto mode, it signals the ticket was under-specified — fix the ticket, not the engine.

## Stage Toggles

- `stages` list in config is authoritative.
- `--stages <csv>` on the CLI overrides.
- Stages not listed are skipped; their `stages/<name>.json` is never written.
- Security stage is implemented but omitted from the default list. In local mode it runs the same stage logic as CI; no local-specific adapter is needed. Enabling it locally requires whatever tooling the stage's prompt expects to be present (e.g., `bandit`).

## MLflow Telemetry

- On by default for local runs; disabled via `--no-track`.
- Backend: local file store at `~/.a2sdlc/mlflow` (single store across all runs and repos).
- Experiment name: the target repo's basename.
- One MLflow run per `run_id`.
- Per-stage metrics (logged as `<stage>.<metric>`): `tokens_in`, `tokens_out`, `turns`, `cost_usd`, `duration_sec`, `model`, `outcome`.
- Rollup metrics: `total_cost_usd`, `total_tokens_in`, `total_tokens_out`, `total_turns`, `total_duration_sec`.
- Quality gate: see **Quality Gate** section below.
- Tags: `run_id`, `model`, `stages_executed`, `git_sha_before`, `git_sha_after`, `dirty_tree_before`, `resumed_from` (if applicable).
- MLflow availability: if the MLflow backend is unreachable and `--no-track` was not passed, the CLI exits with an error before any stage runs. Partial silent loss of eval data is not acceptable.

## Quality Gate

- **When it runs:** only if `implement` was among the executed stages. Running `make check` after spec-only or spec+review runs makes no sense.
- **Where it runs:** after the last executed stage, inside the target repo working tree, on the `a2sdlc/<run_id>` branch.
- **What it does:** shells out to `quality.check_command`, captures stdout/stderr as an MLflow artifact, logs exit code as `quality_passed` (1 if exit 0, else 0).
- **Blocking:** **observational only in v1.** A failing gate does not stop Merge stage from running (Merge in local mode is a no-op push anyway). The signal lives in MLflow for eval purposes.
- **CLI exit code:** the CLI exits non-zero if `quality_passed=0`. This makes the runner usable as a gate in ad-hoc shell scripts even though it doesn't gate pipeline stages internally.

## Resume Semantics

- `--resume <run_id> --from <stage>` re-enters execution at the named stage.
- Loads prior stages' `stages/*.json` state from the run directory.
- Reuses the existing `a2sdlc/<run_id>` branch via `git checkout a2sdlc/<run_id>` (no `-b`).
- Creates a *new* MLflow run tagged `resumed_from=<parent_run_id>`; does not mutate the parent run.
- Re-executing a stage **overwrites** its `stages/<stage>.json`; prior output is not preserved on disk (it lives in the parent MLflow run).

## Failure Modes

- **Crash mid-stage:** stage state is written atomically on stage *completion* only (write to `stages/<stage>.json.tmp`, `os.rename` to final). A partially-executed stage leaves no `stages/<stage>.json`, so `--resume --from <stage>` cleanly re-runs it from the start.
- **Ctrl-C during a stage:** runner catches `KeyboardInterrupt`, marks the active MLflow run as `status=KILLED`, does not write `stages/<stage>.json`. User can resume.
- **MLflow unreachable:** see MLflow Telemetry section — CLI exits with error before any stage runs (unless `--no-track`).
- **`git checkout -b` conflict** (branch already exists and not a resume): CLI exits with a clear error; no silent fallback to a suffixed name.

## Live Console UX

- `adapters/progress/console.py` uses `rich.Live` + `rich.Layout`:
  - **Top pane (scrolling):** stage events — tool calls, outputs — throttled to the engine's existing 5s SDK streaming cadence.
  - **Bottom pane (persistent status bar):** `stage: <name> | tokens: <in>/<out> | cost: $<usd> | turns: <n> | elapsed: <mm:ss> | run: <run_id>`.
- Refresh on every stage event plus a 1Hz tick for smooth elapsed time.
- GitHub Actions uses the existing `::group::` renderer via a different `progress` adapter. The engine sees the same port.

## Post-Run Output

On completion, the runner prints:

```
✓ Run <run_id>   quality: <PASS|FAIL>   cost: $<x.xx>   elapsed: <mm:ss>
  Branch:   a2sdlc/<run_id>
  MLflow:   mlflow ui --backend-store-uri ~/.a2sdlc/mlflow
  Logs:     ~/.a2sdlc/runs/<run_id>/
```

User is left on the run branch. No auto-checkout back to the original branch.

## What Stays Untouched

- `pipeline/dispatch.py`
- `stages/*.py`
- `domain/*`
- `lifecycle/*`
- `assembly/*`
- `evaluation/stats.py` (already captures per-stage cost/token stats that MLflow logging consumes)

## Known Limitations

- **Single-user, single-machine.** MLflow experiment name is the target repo basename, so two different repos with the same basename on different paths collapse into one experiment. Acceptable for v1.
- **Per-stage model override not supported.** Config has a single top-level `model:` value. If some stages should use different models, that's a future config shape (`stages.implement.model`, etc.) — out of scope for v1.

## Open Questions for Implementation Plan

- MLflow dependency weight — should it be an optional extra (`pip install a2sdlc[local]`) or a core dep?
- Where does the CLI entry live — extend `cli.py` or add a `cli_local.py`? Prefer extending `cli.py` to keep one entry point.
- Whether the Jira ticket adapter needs refactoring to conform to the new `TicketAdapter` port, or whether the port can be shaped around the existing Jira code's surface.

## Future Work (out of this spec)

- Taskmaster integration: consume `tasks.json` as an alternative ticket source, loop over tasks in dependency order.
- Per-stage LLM judges (DeepEval) for SPEC quality scoring.
- Question adapters (`terminal`, `answers_file`) once pre-spec maturity warrants questions again.
- Worktree adapter for parallel A/B runs on the same repo.
- `a2sdlc runs prune` subcommand for branch + metadata cleanup.
- Shared MLflow server (Dokploy-hosted) for cross-machine run comparison.
