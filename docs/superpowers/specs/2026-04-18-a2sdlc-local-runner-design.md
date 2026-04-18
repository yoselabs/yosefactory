# a2sdlc Local Runner — Design

**Date:** 2026-04-18
**Status:** Draft, pending user review

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

`.a2sdlc/config.yaml` in the target repo:

```yaml
adapters:
  ticket:   local_file       # alt: jira
  git:      local_branch     # alt: github
  progress: console          # alt: github_actions

stages: [spec, implement, review, merge]   # security off by default

spec:
  mode: auto                 # v1: only mode

quality:
  check_command: "make check"

model: claude-sonnet-4-6
```

CLI flags override any key. Unknown keys are a hard error.

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

- Runner calls `git checkout -b a2sdlc/<run_id>` before stage execution.
- Stage commits happen on that branch in the target repo working tree.
- No push. No remote interaction in the `local_branch` adapter.
- On completion, the user is left on the run branch. Switching back to the original branch is a manual `git checkout`.
- Dirty working tree is not pre-checked; uncommitted changes carry over with the branch switch.
- No prune or cleanup subcommand. Branches accumulate; delete manually.

## Adapter Surface

New adapters in v1:

- `adapters/ticket/local_file.py` — reads ticket markdown from a file path, produces the same domain type that the Jira adapter produces.
- `adapters/git/local_branch.py` — `checkout -b`, stage commits, no push.
- `adapters/progress/console.py` — `rich`-based live console renderer (see "Live Console UX").

Existing `adapters/ticket/jira.py`, `adapters/git/github.py`, and any GH Actions progress renderer remain untouched and are selected by the CI-side config.

Ports (the interfaces the engine imports) are unchanged.

## SPEC in Auto Mode

- `spec.mode: auto` is the only supported value in v1.
- The stage's question-asking code path is gated off when `mode=auto`.
- No question adapter is required in v1.
- Rationale: clarifying questions should be absorbed by a future pre-spec step (done outside a2sdlc). If SPEC asks questions in auto mode, it signals the ticket was under-specified — fix the ticket, not the engine.

## Stage Toggles

- `stages` list in config is authoritative.
- `--stages <csv>` on the CLI overrides.
- Stages not listed are skipped; their `stages/<name>.json` is never written.
- Security stage is implemented but omitted from the default list.

## MLflow Telemetry

- Always on for local runs. `--no-track` disables.
- Backend: local file store at `~/.a2sdlc/mlflow` (single store across all runs and repos).
- Experiment name: the target repo's basename.
- One MLflow run per `run_id`.
- Per-stage metrics (logged as `<stage>.<metric>`): `tokens_in`, `tokens_out`, `turns`, `cost_usd`, `duration_sec`, `model`, `outcome`.
- Rollup metrics: `total_cost_usd`, `total_tokens_in`, `total_tokens_out`, `total_turns`, `total_duration_sec`.
- Quality gate: after the last executed stage, runner shells out to `quality.check_command` in the target repo, logs exit code as `quality_passed` (1 if exit 0, else 0), and logs captured stdout/stderr as an artifact.
- Tags: `run_id`, `model`, `stages_executed`, `git_sha_before`, `git_sha_after`, `resumed_from` (if applicable).

## Resume Semantics

- `--resume <run_id> --from <stage>` re-enters execution at the named stage.
- Loads prior stages' `stages/*.json` state from the run directory.
- Reuses the existing `a2sdlc/<run_id>` branch (assumes it still exists).
- Creates a *new* MLflow run tagged `resumed_from=<parent_run_id>`; does not mutate the parent run.

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

## Open Questions for Implementation Plan

- Exact port shape for the `progress` adapter — does it already exist cleanly, or does it need extraction from existing `evaluation/progress.py`?
- MLflow dependency weight — should it be an optional extra (`pip install a2sdlc[local]`) or a core dep?
- Where does the CLI entry live — extend `cli.py` or add a `cli_local.py`? Prefer extending `cli.py` to keep one entry point.

## Future Work (out of this spec)

- Taskmaster integration: consume `tasks.json` as an alternative ticket source, loop over tasks in dependency order.
- Per-stage LLM judges (DeepEval) for SPEC quality scoring.
- Question adapters (`terminal`, `answers_file`) once pre-spec maturity warrants questions again.
- Worktree adapter for parallel A/B runs on the same repo.
- `a2sdlc runs prune` subcommand for branch + metadata cleanup.
- Shared MLflow server (Dokploy-hosted) for cross-machine run comparison.
