# Local Runner Usage

Run the a2sdlc pipeline locally against any repo, one stage per command. No
Jira, no GitHub, no CI round-trip. Every stage invocation is automatically an
MLflow datapoint.

Design rationale lives in
[`docs/superpowers/specs/2026-04-18-a2sdlc-local-runner-design.md`](superpowers/specs/2026-04-18-a2sdlc-local-runner-design.md).
This doc is reference-only.

## Overview

The local runner is a set of offline adapters (`local_file` work,
`local_noop` review, `local_branch` git, `console` progress) wired into the
existing `dispatch()` core. The engine itself is unchanged. Use it for
prompt/skill iteration, where GitHub CI round-trip is too slow.

## Setup

Requirements:

- Python 3.12, `git`, `uv` (for dev) — same as the engine.
- `mlflow` is a core dependency and is installed by `make bootstrap`.
- The target repo must be a git checkout with at least one commit on the base
  branch (default `main`).

Create `.a2sdlc/config.yaml` in the target repo:

```yaml
adapters:
  work:     local_file
  review:   local_noop
  git:      local_branch
  progress: console

stages: [spec, implement, review, merge]

spec:
  mode: auto

quality:
  check_command: "make check"

default_base: main
model: claude-sonnet-4-6
effort: high  # low | medium | high | xhigh (xhigh → SDK's "max"); omit for SDK default
```

Unknown top-level keys are a hard error. See `src/a2sdlc/config.py` for the
allowlist.

## CLI Reference

```
a2sdlc run-stage <stage> [--session <sid>] [--ticket <file>] [--no-track] <repo>
```

| Argument / flag   | Description |
|---|---|
| `<stage>`         | One of `spec`, `implement`, `review`, `merge`, `security`. |
| `<repo>`          | Path to the target repo (positional, required). |
| `--session <sid>` | Session id. If omitted, inferred from the current branch (`a2sdlc/<sid>`), else a fresh ULID is generated. |
| `--ticket <file>` | Path to a markdown ticket. Required on the first `spec` invocation; ignored afterwards (later stages read `.a2sdlc/ticket.md`). |
| `--no-track`      | Skip MLflow logging. Useful for throwaway runs. Otherwise MLflow must be reachable at `~/.a2sdlc/mlflow` or the CLI exits before running. |

## Session Model

- A **session** = one SPEC → IMPLEMENT → REVIEW → MERGE experiment.
- `session_id` is a ULID. It doubles as `ticket_key`.
- Everything lives on branch `a2sdlc/<session_id>` in the target repo. SPEC
  creates the branch; later stages check it out.
- Re-running a stage in the same session is allowed and overwrites the
  stage's runner-level JSON. MLflow logs each run as a new child run under
  the same session parent.

## State Layout

All engine state lives under `.a2sdlc/` on the session branch:

```
<target_repo>/
  .a2sdlc/
    config.yaml                       project config (you write this)
    state.json                        TicketState — same file CI writes
    ticket.md                         persisted ticket body
    handover/
      spec.md                         SPEC handover — IMPLEMENT reads this
      implement.md
      review.md
    pr.json                           mock PR state (pr_number, status, reviews)
    feedback.json                     REVIEW → next IMPLEMENT feedback
    quality.log                       latest quality-gate output
    runs/<session_id>/
      <stage>.json                    per-stage runner dump (cost, tokens, turns)
      run-<stage>.json                config snapshot per invocation
      logs/<stage>.log                captured console output
    logs/                             CLI logging file handler output
```

Only MLflow lives outside the repo, at `~/.a2sdlc/mlflow`.

## MLflow

Metrics are logged to a local file store at `~/.a2sdlc/mlflow`.

- Experiment name = target repo basename.
- Parent run per session (one per `session_id`).
- Child run per stage invocation. Re-running a stage adds another child.
- Metrics: `tokens_in`, `tokens_out`, `turns`, `cost_usd`, `duration_ms`,
  and `quality_passed` (on IMPLEMENT).
- Tags: `session_id`, `stage`, `git_sha_before`, `dirty_tree_before`.

View the UI:

```bash
mlflow ui --backend-store-uri ~/.a2sdlc/mlflow
```

## Per-Stage Flow

Short summary — see the spec for full detail.

- **spec** — copies `--ticket` to `.a2sdlc/ticket.md`, creates draft PR state
  in `pr.json`, runs the SPEC stage (auto-mode), writes
  `handover/spec.md`.
- **implement** — reads `.a2sdlc/handover/spec.md` via the agent's Read tool,
  edits code on the session branch, writes `handover/implement.md`, runs the
  quality gate, logs `quality_passed` to MLflow.
- **review** — runs REVIEW on the diff; appends a `Review` to `pr.json`. On
  `changes_requested`, writes `feedback.json`. The next IMPLEMENT invocation
  routes through the feedback path automatically.
- **merge** — calls `check_human_approval` (the `local_noop` adapter returns
  a synthetic local approval), flips `pr.json.status = merged`. No push, no
  real merge to base.

## Parallel Runs

Not supported in v1. A single session owns the `a2sdlc/<sid>` branch and the
`.a2sdlc/` directory on it. To A/B two prompts against the same ticket, use
two separate clones of the target repo. A worktree adapter is future work.

## Quality Gate

- Runs at the end of `run-stage implement` only. Does not run after SPEC,
  REVIEW, or MERGE.
- Command is `quality.check_command` from config (default `make check`).
- Stdout + stderr are captured to `.a2sdlc/quality.log` and uploaded as an
  MLflow artifact.
- Observational in v1 — failure does not block subsequent stages, but the
  CLI exits non-zero so CI/wrapper scripts see the failure.

## Troubleshooting

- **`Config not found at .../.a2sdlc/config.yaml`** — create the file using
  the template above. The loader refuses to guess defaults.
- **`Unknown config keys: [...]`** — typo or future-only key. See
  `_ALLOWED_TOP_LEVEL_KEYS` in `src/a2sdlc/config.py`.
- **`error: branch setup failed: ...`** — the session branch could not be
  created or checked out. Usually a dirty tree with changes that conflict
  with the target branch. Commit, stash, or start a fresh session.
- **Dirty tree warning** — non-conflicting uncommitted changes carry over
  silently (git default), and MLflow tags the run with
  `dirty_tree_before=true`. No auto-stash.
- **`--ticket is required on first SPEC invocation`** — the session has no
  `.a2sdlc/ticket.md` yet. Pass `--ticket path/to/ticket.md`.
- **MLflow unreachable** — the CLI exits before running any stage. Pass
  `--no-track` to skip telemetry entirely.
- **REVIEW loops hit a circuit breaker** — `dispatch` blocks after
  `max_review_cycles` (default 2). Either start a new session or edit
  `.a2sdlc/state.json` to reset `review_cycles`.

## Limitations

From the spec's "Known Limitations" section:

- **Single-user, single-machine.** MLflow experiment name is the target repo
  basename; two different repos with the same name collapse into one
  experiment.
- **No per-stage model override.** Config has a single top-level `model:`.
- **Gates default to HUMAN**, and `local_noop_review` returns a synthetic
  approval so MERGE does not block. Exercising real "blocks until human
  approves" behavior locally is future work.
- **Directive `base=...` in the ticket body overrides the runner-captured
  HEAD**, which may surprise users expecting HEAD to win. Documented, not
  fixed.
- **No multi-stage orchestrator.** You invoke one stage at a time. An
  `a2sdlc run` composite command is future work.
- **No parallel runs on the same repo.** Use separate clones.
- **No cleanup/prune subcommand.** Session branches and `.a2sdlc/runs/<sid>/`
  persist until manually removed.
