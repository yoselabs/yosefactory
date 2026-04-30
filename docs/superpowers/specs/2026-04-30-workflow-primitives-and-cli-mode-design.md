---
title: "Workflow primitives and CLI/local mode"
type: spec
status: Draft
owner: "@iorlas"
created: 2026-04-30
updated: 2026-04-30
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (brainstorm session 2026-04-30)"
---

# Workflow primitives and CLI/local mode

## Goal

Establish the engine's workflow vocabulary (Workflow / Activity / Effect /
Signal / Trigger) explicitly, and ship the smallest end-to-end runtime that
exercises it: a CLI / local-mode that runs a full Spec → Implement → Review
cycle on a VM, with no tracker integration and no auto-merge.

The cycle takes a base branch carrying an `INPUT.md` requirement, generates
a per-attempt run branch, drives the agent through stages, supports the
review→implement handover loop, writes review artifacts to branch state, and
pushes the run branch to origin. Output is the run-branch name plus an
optional preview URL on stdout.

This is V1 of a future-portable architecture: the workflow primitives are
designed to map cleanly to Temporal (or any durable workflow engine) without
introducing engine-specific concepts now. Tracker-driven triggers,
auto-merge, multi-pipeline coordination, and human-gate signals are
deliberately deferred — additive later, never breaking changes.

Appetite: **5–7 days** (model rename + composition reshuffle + new
adapter + CLI surface + tests).

## Non-goals

- **No auto-merge.** Run branches accumulate as the audit trail. The Merge
  stage is not on the v1 critical path.
- **No tracker integration in v1.** GitHub WorkAdapter and Jira WorkAdapter
  remain *future* compositions. v1 ships only the local file/CLI mode.
- **No third identifier beyond `workflow_id` + `ticket_key`.** Eval and
  rework both reduce to "new run branch with same `ticket_key`."
- **No eval mode in v1.** Eval-orchestration is an out-of-engine concern
  (a script that fans out N `a2sdlc run` invocations) and not part of
  v1's contract.
- **No durable run-registry ref.** State stays branch-local. Branch lifecycle
  = workflow lifecycle.
- **No protocol split of `ReviewAdapter` into `ReviewOutputAdapter` +
  `PRLifecycleAdapter`.** Note as a future cleanup; defer.
- **No feature-flagging / `workflow.patched` analogue.** Forward-compat is
  via `state.json`'s `schema_version`, not code-path versioning.
- **No multi-concurrent runs on one VM.** Single run per VM is supported;
  worktrees come later.

## Workflow vocabulary

The engine has five concepts. They already exist in the codebase under
different names; this spec promotes them to first-class.

| Concept | Definition | Today's home |
|---|---|---|
| **Workflow** | Durable identity + state machine for one execution attempt of a work item. Identified by branch name. State serialized as `state.json` on the branch. | Implicit; state lives in `state.json` |
| **Trigger** | An event source that *starts* a workflow. CLI `run` is the only trigger in v1. | `cli/`, `subscriber/gh_actions.py` |
| **Activity** | A unit of side-effecting work invoked from inside a stage handler (LLM call, git op, file read). Idempotency keys are explicit. | Stage handlers do these directly |
| **Effect** | A *description* of a state-changing outcome a stage emits, applied by the engine outside handler code. | `effects/apply.py`, `effects/stage_finish.py` |
| **Signal** | A typed external decision delivered to a workflow. Not exercised in v1 (no auto-merge means no human-gate signals). Defined for forward-compat. | Not yet present |

The model collapses to: *a workflow is a pure reducer over its state and
incoming events; activities and effects are the I/O boundary; signals are
the external-decision boundary; triggers spawn workflows*. This shape is
preserved when a future runtime (Temporal, Restate, etc.) replaces the
in-process loop.

## Identity model

Two identifiers, no third:

```
PipelineRun {
  workflow_id:    str        # = run-branch name; unique per attempt
  ticket_key:     str | None # = "ABC-123" or label or filename slug; shared across attempts
  base:           str        # base branch name
  base_sha:       str        # base branch HEAD at workflow start
  version:        int        # auto-incremented from existing run branches for the same base
  ecosystem:      str        # = config.mode value: "local" | "github" | "jira-github"
  schema_version: int        # state.json schema version
  stage:          StageName  # current stage
  ...                        # plus existing fields: pr_number (None in v1), branch, etc.
}
```

`workflow_id` is engine-internal addressing. `ticket_key` is for humans,
telemetry, and (future) tracker correlation. Telemetry envelopes carry both.

**Branch-name-as-workflow-id is a load-bearing invariant.** State must only
be loaded when its `state.branch == current_branch`. The `_ensure_draft_pr`
guard at `pipeline/dispatch.py:90` becomes a general rule applied wherever
`state.json` is read.

## Run-branch suffix

The run-branch generator produces:

```
a2sdlc/auto/<base-slug>/<yyyymmdd-hhmm>-<input-hash>
```

- `<base-slug>` = base branch name with `/` → `-`
- `<input-hash>` = first 6 hex chars of SHA-256 of `INPUT.md` content
  at base HEAD

Hash suffix gives a reproducibility marker — running twice with identical
input produces the same hash, making accidental duplicate runs detectable.
Time prefix gives ordering for human inspection.

## State storage and lifecycle

State remains at `.a2sdlc/state/<branch-derived-path>/state.json` on the
run branch. No new git refs, no separate registry, no external store.

**Cleanup rule: state cleanup is the merge stage's responsibility, and the
merge stage does not run in v1.** State files therefore persist on run
branches indefinitely as audit artifacts, alongside review output and the
final code. This is intentional: branches are the audit trail.

The schema gains `schema_version: int` and the new identity fields above.

## Adapter ecosystem

Adapters group by *ecosystem*, not by concern. Ecosystems are wired
together; you don't mix-and-match within v1. Future ecosystems (github,
jira+github) are additive.

### Local ecosystem (v1)

| Role | Adapter | Behavior |
|---|---|---|
| Work | `LocalFileWorkAdapter` (existing, extended) | Reads `INPUT.md` from base HEAD as the "ticket"; progress comments go to `.a2sdlc/state/<branch>/progress.md`; status transitions update local markers. |
| Review | **`LocalReviewAdapter` (new)** | `post_review` writes `.a2sdlc/state/<branch>/reviews/<ts>-cycle-<n>.md`; `post_inline_comments` writes `<ts>-cycle-<n>-inline.md` with `path:line — comment` form. PR-lifecycle methods (`create_draft_pr`, `merge_pr`, `mark_pr_ready`, `get_approvals`) return safe no-op defaults. |
| Subscribers | `console`, `mlflow_trace` | Console prints stage transitions to stdout; MLflow records run metadata. |

`LocalNoopReviewAdapter` is preserved for tests that want a true no-op; the
new `LocalReviewAdapter` is the user-facing local mode that produces
inspectable artifacts.

### Future ecosystems (deferred)

Not implemented in v1. Listed only to confirm the protocol survives:

| Role | github ecosystem | jira+github ecosystem |
|---|---|---|
| Work | `GitHubWorkAdapter` | `JiraWorkAdapter` |
| Review | `GitHubReviewAdapter` | `GitHubReviewAdapter` |
| Subscribers | `gh_actions`, `gh_comment` | `gh_actions`, `jira_comment` |

`ReviewAdapter` Protocol is *not* split in v1. If a third review ecosystem
later squeezes against the PR-lifecycle methods, that's the signal to split
into `ReviewOutputAdapter` + `PRLifecycleAdapter`. Recorded as future work.

## Composition: config-file driven

Adapter selection lives in repo config, not CLI flags:

```
# .a2sdlc/config.yaml (or pyproject [tool.a2sdlc])
mode: local              # local | github | jira-github (only "local" implemented in v1)
adapters:
  work: local-file
  review: local
subscribers:
  - console
  - mlflow
required_env:
  - ANTHROPIC_API_KEY
```

The `a2sdlc run` command is a **universal verb**, not local-only. It reads
the config to pick adapters, applies any CLI flag overrides, then dispatches.
The same command runs in CI later by pointing at a different config (or
overriding `--mode`).

CLI flag overrides supported:

- `--base <branch>` — override auto-detected base
- `--config <path>` — override config-file location
- `--label <name>` — set `ticket_key` explicitly
- `--mode <mode>` — override `mode` from config (`local` | `github` |
  `jira-github`); CI uses this

## CLI surface (`a2sdlc run`)

Behavior, in this order:

1. **Validate environment first.** Resolve config, load adapter set,
   validate required env vars (see below). This is the very first action
   so missing-credential failures cost sub-second time.
2. **Resolve base.** `--base` arg if given, else current `HEAD` ref name.
   Refuse if base is in the protected set (`main`, `master`, configurable
   in `.a2sdlc/config.yaml` under `protected_bases`) unless
   `--allow-protected-base` is passed.
3. **Read `INPUT.md` from base HEAD** (the committed version, not the
   working tree). Error if missing on base HEAD. Reasoning: input must be
   committed for audit. The working-tree state of `INPUT.md` is ignored
   on purpose so BA's local edits can't accidentally drive a run.
4. **Compute hash, generate run-branch name, create branch off base,
   switch to it.**
5. **Run pipeline** SPEC → IMPLEMENT → REVIEW, with handover loop
   (REVIEW → IMPLEMENT) up to `max_review_cycles` (default 3, configurable
   under `pipeline.max_review_cycles`).
6. **Persist progress after each stage.** Commit (a) updated `state.json`,
   (b) any code changes the stage produced, (c) any new review artifacts
   under `.a2sdlc/state/<branch>/reviews/`, then `git push origin
   <run-branch>`. Push failures fail the run with a clear error; partial
   state stays local for forensics.
7. **Print stage transitions to stdout** in real time via the `console`
   subscriber.
8. **On terminal state**, print the run-branch name on stdout and exit
   0. Preview-URL emission is out of scope for v1 — left for a later
   subscriber plugin.

Sample output:

```
$ a2sdlc run
[SPEC]      reading INPUT.md from req/billing-v2 ...
[SPEC]      done → IMPLEMENT
[IMPLEMENT] generating changes ...
[IMPLEMENT] done → REVIEW
[REVIEW]    inspecting diff ...
[REVIEW]    handover → IMPLEMENT (feedback: "missing edge case for X")
[IMPLEMENT] revising ...
[IMPLEMENT] done → REVIEW
[REVIEW]    approved
done.
branch: a2sdlc/auto/req-billing-v2/20260430-1422-a3f019
```

## Fail-fast on missing env vars

Each adapter declares its required environment variables as a class
attribute:

```python
class LocalFileWorkAdapter:
    REQUIRED_ENV: tuple[str, ...] = ()

class GitHubWorkAdapter:
    REQUIRED_ENV: tuple[str, ...] = ("GITHUB_TOKEN",)
```

The composition root collects `REQUIRED_ENV` across all wired adapters
plus engine-level required vars (e.g. `ANTHROPIC_API_KEY`), and validates
`os.environ` **before any I/O happens**. Missing vars are aggregated into a
single error message that lists every missing key:

```
$ a2sdlc run
error: required environment variables are not set:
  - ANTHROPIC_API_KEY  (engine)
  - GITHUB_TOKEN       (adapter: github-work)
set them in your shell or .envrc and try again.
exit 2
```

The check runs before reading `INPUT.md` or touching git, so missing
credentials cost a sub-second response, not a half-completed run.

## MLflow correlation

Every run logs to MLflow with:

- **`run_name`** = `workflow_id` (= run-branch name) — direct findability
- **Tags:**
  - `ticket_key` — when set
  - `base` — base branch name
  - `base_sha` — base commit SHA at run start
  - `version` — version counter
  - `ecosystem` — `local` | `github` | `jira-github`
  - `input_hash` — 6-char hash from run-branch suffix
  - `engine_version` — git SHA of the engine release
- **Metrics:** stage durations, total wall time, total tokens, total cost
  (where measurable), number of review cycles
- **Artifacts:** copy of `INPUT.md`, final state.json, review markdown
  files

This lets BA (or you) filter MLflow by `ticket_key` or `base` to compare
attempts on cost / speed / cycle-count. Run name = branch name means a
single click jumps from MLflow to the actual code.

## Effects, signals, triggers — explicit boundaries

### Effects (already exist; lock the boundary)

Stage handlers return a list of effect descriptions. `effects/apply.py`
applies them. v1 enforces this contract — handler code must not perform
cross-cutting I/O directly. Existing handlers already mostly conform;
audit and tighten in implementation.

### Signals (defined, unexercised in v1)

A `Signal` is a typed envelope:

```
Signal {
  workflow_id:  str
  kind:         SignalKind   # MERGE_APPROVAL, RETRY, CANCEL, ...
  payload:      dict
  actor:        str
  ts:           datetime
}
```

No signal kinds are wired up in v1 (no auto-merge, no human gates). The
envelope type and a stub dispatch path (engine accepts a `Signal` and
routes by `workflow_id`, but v1 has no consumers) are defined so that
adding a `MERGE_APPROVAL` signal later is purely additive. The future tracker-label adapter
translates label events into `Signal` envelopes; the engine routes by
`workflow_id`.

### Triggers (one in v1)

A `Trigger` produces a workflow-start event. v1 has one: `cli`. Its
payload:

```
StartWorkflow {
  base:         str
  input_path:   str             # = "INPUT.md" relative to base HEAD
  label:        str | None
  config_path:  str | None
  mode:         Mode
}
```

Future triggers (`github-webhook`, `jira-webhook`, custom event systems)
produce the same `StartWorkflow` shape with different sources. Engine
doesn't care which trigger fired.

## Migration notes

- Existing `state.json` consumers gain a `schema_version` check; v0 files
  without the field are treated as v0 and migrated on read.
- `RunIntent.base` already carries the base branch — wire `base_sha`
  capture at workflow start.
- `format_branch` becomes adapter-driven for both directions: existing
  `format_branch(ticket_key)` for the GH ecosystem, plus new
  `format_run_branch(base, input_hash, ts) -> str` for the local ecosystem.
- The `merge` stage is removed from the v1 default pipeline (still exists
  in code; just not in the local-mode stage list).

## Acceptance criteria

1. A fresh repo with `INPUT.md` on a `req/*` branch and a minimal
   `.a2sdlc/config.yaml` runs end-to-end via `a2sdlc run` on a VM, produces
   a run branch on origin, writes review artifacts under
   `.a2sdlc/state/<branch>/reviews/`, and prints the branch name.
2. Re-running with the same `INPUT.md` produces a branch with the same
   hash suffix (different timestamp); BA can detect duplicates.
3. Re-running after editing `INPUT.md` produces a branch with a different
   hash suffix.
4. Removing a required env var causes the CLI to exit non-zero in
   sub-second time, listing every missing var by name and which adapter
   needs it.
5. MLflow shows the run with `run_name = <branch-name>` and pivotable
   tags (`ticket_key`, `base`, etc.).
6. Review handover loop fires at least once when the spec demands it,
   visible as `REVIEW → IMPLEMENT` transitions in stdout and as multiple
   `<ts>-cycle-<n>.md` files in the review folder.
7. Engine refuses to run on a protected base (`main`) without an
   explicit `--allow-protected-base` flag.
8. Architecture tests still pass — domain has zero a2sdlc imports;
   composition root remains the only 5+-package importer.

## Out-of-scope follow-ups (already enumerated, captured here for tracking)

These are deliberately deferred and have their own future specs:

- **Spec 2 — Adapter capability protocol.** Inline-comment capability
  discovery, custom event-system trigger interface, ecosystem split of
  `ReviewAdapter` if needed.
- **Spec 3 — Stage extensibility & agent recipes.** Third-party stages,
  per-repo prompt/skill overrides, reusable review agent as a recipe
  building block.
- **Auto-merge mode.** Re-introduces the merge stage and human-gate
  signals as opt-in.
- **Tracker-driven triggers.** GitHub webhook adapter, Jira adapter,
  signal envelopes wired to label events.
- **Multi-concurrent runs.** Worktree-based isolation on a single VM.
- **Eval orchestration.** Out-of-engine script that fans out N
  invocations and aggregates MLflow runs.
