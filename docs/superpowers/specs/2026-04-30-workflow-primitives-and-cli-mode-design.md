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

Appetite: **10–12 days.** The vocabulary (Workflow / Activity / Effect /
Signal / Trigger) stays *documentation-level* in v1 — code keeps existing
type names — but the runtime surface added here is real engineering:
`LocalReviewAdapter`, the new `WorkAdapter.write_stage_artifact` method
and `LocalFileWorkAdapter` impl, the `ReviewAdapter.post_review` return
type change to `Path`, the run-branch generator + parser pair, env-var
validation + REQUIRED_ENV plumbing, lockfile + signal-handler cleanup,
dirty-tree check, lazy v0→v1 migration, the failure-modes-table error
surface, the `StageEnd.artifact_path` extension + new
`_format_tokens_precise` helper + `RunEnd` event, the console
subscriber's three-rhythm renderer (start / event log / output block +
stats / totals), and the `make smoke-local` end-to-end harness with its
local-origin git plumbing. Doing a real type rename of the vocabulary
inside the codebase is out of scope and would push to 14+ days.

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
- **No durable run-registry ref.** State stays branch-local. Branch
  lifecycle = workflow lifecycle (single home for this rule; not
  restated elsewhere).
- **No protocol split of `ReviewAdapter` into `ReviewOutputAdapter` +
  `PRLifecycleAdapter`.** Note as a future cleanup; defer.
- **No feature-flagging / `workflow.patched` analogue.** Forward-compat is
  via `state.json`'s `schema_version`, not code-path versioning.
- **No multi-concurrent runs on one VM.** Single run per VM is supported;
  worktrees come later. v1 enforces the constraint with a PID lockfile;
  see §Failure modes for the exact lockfile + stale-lock semantics.
- **No code rename of existing types** to the new vocabulary. The
  vocabulary is documentation-level; type names in the codebase stay as
  they are. Carve-outs (additive, not renames): adding `RunEnd` to the
  `ProgressEvent` taxonomy; adding `artifact_path: Path | None` field
  to `StageEnd`; adding `WorkAdapter.write_stage_artifact` method;
  adding `_format_tokens_precise` helper. Carve-out (acknowledged
  signature change, not a rename): `ReviewAdapter.post_review` return
  type changes from `None` to `Path`. All existing call sites update
  in this v1 effort.

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

**Storage caveat for Temporal portability.** The *primitives* port cleanly;
the *storage* does not. Temporal owns workflow state in its cluster, and
its `workflow_id` is a durable cluster identity decoupled from any external
resource — the opposite of "branch death = workflow death." On a Temporal
migration: `state.json` becomes a derived read-model written by activities,
durable identity moves to Temporal's `workflow_id`, and the branch becomes
a tag on that workflow. The reducer, the effect descriptions, and the
signal envelopes survive intact; the persistence layer is rewritten.

## Identity model

Two identifiers, no third:

```
PipelineRun {
  workflow_id:    str        # = run-branch name; unique per attempt
  ticket_key:     str | None # = "ABC-123" or label or filename slug; shared across attempts
  base:           str        # base branch name
  base_sha:       str        # base branch HEAD at workflow start
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
a2sdlc/auto/<base-slug>/<yyyymmdd-hhmmss>-<input-hash>
```

- `<base-slug>` = base branch name with `/` → `-`
- `<input-hash>` = first 6 hex chars of SHA-256 of `INPUT.md` content
  at base HEAD
- Timestamp uses **second** precision (UTC) to make collisions on
  back-to-back reruns mathematically impossible in practice.

Hash suffix gives a reproducibility marker — running twice with identical
input produces the same hash, making accidental duplicate runs detectable.
Time prefix gives ordering for human inspection. If a branch with the
generated name already exists locally or on origin (e.g. clock skew or
deliberate retry within the same second), the engine refuses with a clear
error — see §Failure modes.

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
| Work | `LocalFileWorkAdapter` (existing, extended) | Reads `INPUT.md` from base HEAD as the "ticket"; progress/status markers go to `.a2sdlc/state/<branch>/progress.md`; **stage handlers write per-stage artifacts** via the new `WorkAdapter.write_stage_artifact` method (see below): SPEC writes `.a2sdlc/state/<branch>/spec.md` (one file per workflow; SPEC runs only `cycle 1`); IMPLEMENT writes `.a2sdlc/state/<branch>/implement-cycle-<n>.md` (one per cycle). |
| Review | **`LocalReviewAdapter` (new)** | `post_review` writes `.a2sdlc/state/<branch>/reviews/<ts>-cycle-<n>.md`; `post_inline_comments` writes `<ts>-cycle-<n>-inline.md` (format below). PR-lifecycle methods (`create_draft_pr`, `merge_pr`, `mark_pr_ready`, `get_approvals`) return safe no-op defaults. |
| Subscribers | `console`, `mlflow_trace` | Console prints stage transitions and per-stage stats summaries (duration / turns / tokens / cost) to stdout, plus a final `totals:` line; MLflow records the same numbers as run metrics. |

`LocalNoopReviewAdapter` is preserved for tests that want a true no-op; the
new `LocalReviewAdapter` is the user-facing local mode that produces
inspectable artifacts.

**New `WorkAdapter` method (additive, not a rename).** The protocol gains
one method to make the artifact-write seam explicit and the output-block
byte-equality enforceable:

```python
def write_stage_artifact(
    self, stage: StageName, cycle: int, content: str
) -> Path: ...
```

Implementations decide *where* the file lands (LocalFileWorkAdapter
returns `.a2sdlc/state/<branch>/<stage>[-cycle-<n>].md`; future
GitHubWorkAdapter could write the same to a tracker comment); the
returned `Path` is what the `console` subscriber reads to populate the
output block. This way the file content and the stdout block are the
same `bytes` object — the byte-equality claim in AC #13 is enforceable
by a single read.

The method is **additive** (no existing call sites change) and is
explicitly carved out of the "no code renames" non-goal in the same
spirit as `RunEnd`.

Inline-comment file format. One block per comment, blank line between
blocks. Multi-line comment bodies are kept verbatim under the header:

```
src/billing/charge.py:42
  agent: payment retries can wedge here when the upstream API returns 502
  on idempotency-key re-use; consider an explicit retry-count cap.

src/billing/charge.py:88
  agent: missing edge case — empty cart still hits the charge endpoint.
```

`path:line` is the header, indented body lines are the comment. Encoding
is UTF-8. The em-dash is illustrative; any character is allowed in the
body.

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

```yaml
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
pipeline:
  max_review_cycles: 3   # SPEC → IMPLEMENT → REVIEW handover loop cap
  protected_bases:       # bases the engine refuses unless --allow-protected-base
    - main
    - master
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

1. **Validate environment first.** Resolve the config file path (default
   `.a2sdlc/config.yaml`, override with `--config`), load adapter classes
   (no instantiation, no I/O), and validate required env vars from each
   class's static `REQUIRED_ENV` plus engine-level vars. This step touches
   the config file and `os.environ` only — no git, no FS reads beyond the
   config — so missing-credential failures cost sub-second time.
2. **Acquire VM lockfile** at `.a2sdlc/run.lock` (exclusive flock with PID
   + start-timestamp). Fail with a clear error if held by another process.
   See §Failure modes.
3. **Resolve base.** `--base` arg if given, else current `HEAD` ref name.
   Refuse if base is in `pipeline.protected_bases` (default `[main,
   master]`) unless `--allow-protected-base` is passed.
4. **Reject dirty working tree.** If `git status --porcelain` reports any
   tracked changes, fail. The engine never silently consumes uncommitted
   work. Untracked files outside `.a2sdlc/` are tolerated (BAs may have
   notes lying around).
5. **Read `INPUT.md` from base HEAD** (the committed version, not the
   working tree). Error if missing on base HEAD. Reasoning: input must be
   committed for audit. The working-tree state of `INPUT.md` is ignored
   on purpose so BA's local edits can't accidentally drive a run.
6. **Compute hash, generate run-branch name, refuse if branch already
   exists** locally or on origin, then create branch off base and switch
   to it.
7. **Run pipeline** SPEC → IMPLEMENT → REVIEW, with handover loop
   (REVIEW → IMPLEMENT) up to `pipeline.max_review_cycles` (default 3).
8. **Persist progress after each stage.** Commit (a) updated `state.json`,
   (b) any code changes the stage produced, (c) any new review artifacts
   under `.a2sdlc/state/<branch>/reviews/`, then `git push origin
   <run-branch>`. Each stage advance = one commit. Commit and push are
   each fatal on failure — see §Failure modes for the recovery surface.
9. **Print stage transitions to stdout** in real time via the `console`
   subscriber.
10. **On terminal state**, print the run-branch name on stdout and exit
    0. Preview-URL emission is out of scope for v1 — left for a later
    subscriber plugin.
11. **Release the lockfile** on exit (success or failure).

### Console output cadence

Three sections per stage, all driven from the existing `ProgressEvent`
stream (`domain/progress.py`) routed through the `console` subscriber:

1. **Stage start** — one line when a stage begins, naming the stage and
   the cycle number for re-entries: `[SPEC] starting (cycle 1)`.
2. **Mid-stage event log** — every progress event renders, including
   tool calls. No throttling — local-mode is for inspection on a VM,
   verbose is helpful. One line per event, prefixed with the stage tag
   and indented for tool-call detail. `Milestone` events render as
   plain prefixed lines; `GroupOpen` / `GroupClose` render as
   pass-through scope markers (single line, no nesting indent in v1)
   so the implementer doesn't have to invent a tree renderer.

   The `cycle N` counter on the `starting` line is **per-stage,
   always starts at 1, increments on each re-entry** of that stage
   (SPEC will always show `cycle 1`; IMPLEMENT and REVIEW will
   increment when the handover loop fires).
3. **Stage end** — two blocks at the terminal transition (`done` /
   `handover` / `approved`):
   - **Output block.** The stage's primary artifact rendered inline.
     For each stage, the artifact is the file the active adapter
     writes for that stage's output (single source, two sinks: file +
     stdout):
     - **SPEC** → `.a2sdlc/state/<branch>/spec.md`
       (written by `LocalFileWorkAdapter`)
     - **IMPLEMENT** → `.a2sdlc/state/<branch>/implement-cycle-<n>.md`
       (written by `LocalFileWorkAdapter`)
     - **REVIEW** → `.a2sdlc/state/<branch>/reviews/<ts>-cycle-<n>.md`
       (written by `LocalReviewAdapter`; if the review produced inline
       comments, the paired `<ts>-cycle-<n>-inline.md` is appended to
       the same block)
     Block is fenced with the banner-style markers below so the fence
     cannot collide with arbitrary markdown the artifact contains:
     ```
     ===== a2sdlc:stage-output BEGIN =====
     <artifact bytes>
     ===== a2sdlc:stage-output END =====
     ```
   - **Stats line.** `<duration> · <turns> turns · <tokens-in> in /
     <tokens-out> out · <cost>`. Wiring: the existing
     `StageEnd.final_metrics: Metrics` field already carries the same
     five numbers under different field names (`input_tokens`,
     `output_tokens`, `total_cost_usd`, `num_turns`, `elapsed`). The
     console subscriber **derives** the stats line directly from
     `final_metrics` — no schema change to `StageEnd`, no parallel
     `stage_stats` field. `domain/stats.py` `StageRunStats` remains
     the per-stage retry accumulator used inside dispatch; the
     console renderer doesn't read it.

   **Artifact path routing.** The output block must be byte-equal to
   the file the active adapter wrote. To avoid making the console
   subscriber adapter-aware (it shouldn't know about
   `WorkAdapter` / `ReviewAdapter`), the artifact path rides on the
   event itself: `StageEnd` is extended with one new field,
   `artifact_path: Path | None` (additive, default `None` so existing
   constructors stay compatible). Dispatch sets it from the path the
   active adapter returned at stage finish:

   - **SPEC / IMPLEMENT** → path returned by
     `WorkAdapter.write_stage_artifact(...)`.
   - **REVIEW** → path returned by `LocalReviewAdapter.post_review(...)`.
     `ReviewAdapter.post_review` gains a return-type change from
     `None` to `Path` — this **is** a breaking change to the protocol
     and is explicitly carved out in the same way as
     `write_stage_artifact`. `GitHubReviewAdapter` and
     `LocalNoopReviewAdapter` get the trivial impl
     (`return Path("/dev/null")` for noop; the file the GH adapter
     stages locally before posting for the GH impl). When REVIEW also
     produced inline comments, dispatch concatenates the inline file
     onto the main artifact bytes when reading for the output block —
     `artifact_path` still references the primary review file.

   `artifact_path is None` means "no output block to render" (e.g. a
   stage that ends in error before producing artifacts); console
   skips the block, prints only the stats line.
4. **Run end** — a `totals:` aggregate line over all stage runs. Wiring:
   `pipeline/dispatch.py` emits a new `RunEnd` event in a `finally`
   block so it fires on **both success and failure paths**. The
   `console` subscriber prints the line as `totals:` on success or
   `totals (failed):` when `RunEnd.success == False`. Adding `RunEnd`
   to `domain/progress.py` is a code-level addition explicitly carved
   out from the "no code renames" non-goal — additive event, not a
   rename.

   `RunEnd` shape:

   ```python
   @dataclass(frozen=True)
   class RunEnd:
       workflow_id:     str
       success:         bool
       error:           str | None        # populated on failure paths
       aggregate_stats: StageRunStats     # summed across all stage runs
       total_cycles:    dict[StageName, int]  # cycles per stage (e.g., {SPEC:1, IMPLEMENT:2, REVIEW:2})
   ```

   **Provenance of `total_cycles` and `aggregate_stats`.** Both come
   from `state.json`, which is the source of truth for cycle counts
   (the handover loop must persist them so it can enforce
   `max_review_cycles` across restarts). On terminal exit (success or
   failure-via-`finally`), dispatch reads `state.json` one last time,
   builds `RunEnd`, and emits it before releasing the lockfile. If
   `state.json` is missing or unreadable (catastrophic case, e.g. the
   run failed before step 6 of CLI surface), `RunEnd` is emitted with
   `total_cycles={}` and `aggregate_stats=StageRunStats()` (zeros)
   plus `success=False` and the error.

   Even on failure paths from §Failure modes (commit failure, push
   failure, max_review_cycles exceeded, internal/unhandled), `RunEnd`
   captures whatever stages did run before the failure. AC #12 covers
   the success case; `totals (failed):` rendering is asserted by AC
   #14 (added below).

The `_throttle.py` utility stays available for future ecosystems
(github mode posts comments and *will* want throttling), but the
`console` subscriber does not use it in v1.

Sample output:

```
$ a2sdlc run
[SPEC]      starting (cycle 1)
[SPEC]      tool: read INPUT.md
[SPEC]      tool: read docs/architecture.md
[SPEC]      tool: write .a2sdlc/state/.../spec.md
===== a2sdlc:stage-output BEGIN =====
## Acceptance criteria
1. Charges with valid card succeed and return 2xx.
2. Charges with empty cart return 400 with code EMPTY_CART.
3. Idempotency-key reuse on the same cart returns the original charge.
===== a2sdlc:stage-output END =====
[SPEC]      done → IMPLEMENT     | 18.3s · 4 turns · 12.4k in / 3.1k out · $0.082

[IMPLEMENT] starting (cycle 1)
[IMPLEMENT] tool: edit src/billing/charge.py
[IMPLEMENT] tool: edit src/billing/charge.py
[IMPLEMENT] tool: write tests/billing/test_charge.py
[IMPLEMENT] tool: bash 'pytest tests/billing -x'
===== a2sdlc:stage-output BEGIN =====
Edited src/billing/charge.py: added EMPTY_CART guard at line 42.
Added tests/billing/test_charge.py with 3 cases (success, empty-cart, idempotency).
All tests pass.
===== a2sdlc:stage-output END =====
[IMPLEMENT] done → REVIEW        | 2m 41s · 9 turns · 38.2k in / 14.7k out · $0.412

[REVIEW]    starting (cycle 1)
[REVIEW]    tool: read src/billing/charge.py
[REVIEW]    tool: read tests/billing/test_charge.py
===== a2sdlc:stage-output BEGIN =====
verdict: changes_requested

src/billing/charge.py:88
  agent: missing edge case for X — empty cart still hits the upstream API
  when payment_method has retry_on_empty=True. add a guard before
  line 88 or hoist the EMPTY_CART check.
===== a2sdlc:stage-output END =====
[REVIEW]    handover → IMPLEMENT | 41.2s · 3 turns · 22.1k in / 1.8k out · $0.071

[IMPLEMENT] starting (cycle 2)
[IMPLEMENT] tool: edit src/billing/charge.py
[IMPLEMENT] tool: bash 'pytest tests/billing -x'
===== a2sdlc:stage-output BEGIN =====
Hoisted EMPTY_CART guard above the retry path. All tests pass.
===== a2sdlc:stage-output END =====
[IMPLEMENT] done → REVIEW        | 1m 04s · 5 turns · 19.8k in / 6.2k out · $0.184

[REVIEW]    starting (cycle 2)
[REVIEW]    tool: read src/billing/charge.py
===== a2sdlc:stage-output BEGIN =====
verdict: approved
===== a2sdlc:stage-output END =====
[REVIEW]    approved             | 12.8s · 2 turns · 14.6k in / 0.4k out · $0.041

done.
branch: a2sdlc/auto/req-billing-v2/20260430-142208-a3f019
totals: 5m 17s · 23 turns · 107.1k in / 26.2k out · $0.790
```

**Stats line formatting.** Two formatters reuse existing helpers, one
is added new:

- **Duration** — reuse `domain/progress_format._format_duration(seconds)`
  unchanged. Console calls it as
  `_format_duration(stage_run_stats.duration_ms / 1000)`. Yields `Xs`
  under 60s, `Xm Ys` from 1m to 1h, `Xh Ym` above. Sub-second values
  render as `0s` (the helper truncates with `int()`).
- **Tokens (in / out)** — **add a new sibling helper**
  `_format_tokens_precise(n)` in `domain/progress_format.py`. Existing
  `_format_tokens(n)` returns integer `{k}k` (clamped to `1k` for any
  positive n < 1500) which is fine for the status bar but too coarse
  for stats lines. The new helper renders:
  - `0` → `"0"`
  - `1 ≤ n < 1000` → `"{n}"` (no suffix)
  - `1000 ≤ n < 1_000_000` → `f"{n/1000:.1f}k"` (e.g. `12_400 → "12.4k"`)
  - `n ≥ 1_000_000` → `f"{n/1_000_000:.1f}M"` (e.g. `2_500_000 → "2.5M"`)
  Existing `_format_tokens` is unchanged — no ripple to status-bar
  callers.
- **Cost** — `f"${cost_usd:.2f}"` always two decimals; `0.0` renders
  as `$0.00` (used for free local models so the line shape is stable).

If a stat is unavailable for a stage (e.g. a stage that doesn't call
the LLM), the field is rendered as `-` rather than omitted, so the line
shape stays alignable in stdout.

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
`os.environ` **before any I/O happens** (config file read excepted —
that's how we know which adapters to ask). Missing vars are aggregated
into a single error message; format and exit code are specified in
§Failure modes.

The check runs before lockfile acquisition, base resolution, or any git
read, so missing credentials cost a sub-second response, not a
half-completed run.

## Failure modes

Single source of truth for what fails, what message the BA sees, and what
exit code the CLI returns. Implementers must not invent new modes; they
must add to this table.

| When | Detection | Stderr message (paraphrased) | Exit | Recovery |
|---|---|---|---|---|
| Required env var missing | Step 1 | `error: required environment variables are not set:\n  - VAR (engine)\n  - VAR2 (adapter: github-work)\nset them in your shell or .envrc and try again.` | 2 | Set vars, rerun. |
| Lockfile already held | Step 2 | `error: another a2sdlc run is in progress on this VM (pid <P> started <T>). only one run at a time is supported.` | 3 | Wait for prior run, or kill stale process and remove `.a2sdlc/run.lock`. |
| Protected base | Step 3 | `error: refusing to run on protected base '<branch>'. pass --allow-protected-base to override.` | 4 | Use `--allow-protected-base` or check out a non-protected base. |
| Dirty working tree | Step 4 | `error: working tree has uncommitted changes:\n<short status>\ncommit, stash, or reset before running.` | 5 | Resolve, rerun. |
| `INPUT.md` missing on base HEAD | Step 5 | `error: INPUT.md not found on '<base>' HEAD. commit it on the base branch and try again.` | 6 | Commit `INPUT.md` to base, rerun. |
| Run-branch already exists | Step 6 | `error: branch '<run-branch>' already exists (local or origin). a duplicate run with the same INPUT.md within the same second is unsupported.` | 7 | Wait one second, rerun. |
| Stage-commit failure (e.g. pre-commit hook) | Step 8 | `error: failed to commit stage '<n>' progress: <git stderr>\nlocal branch '<run-branch>' on this VM has the partial state.` | 8 | Inspect locally, fix, manually finish or discard. |
| Push failure | Step 8 | `error: failed to push '<run-branch>' to origin: <git stderr>\nlocal branch on this VM has the work — run 'git push origin <run-branch>' manually after fixing.` | 9 | Push manually or rerun after resolving. |
| `max_review_cycles` exceeded | Step 7 | `error: review handover loop exceeded max_review_cycles=<N>. last review at <ts>. branch '<run-branch>' kept for inspection.` | 10 | Inspect reviews, edit `INPUT.md` on base, rerun. |
| Internal/unhandled | anywhere | `error: internal failure: <traceback>\nlockfile released; partial state on local branch '<run-branch>'.` | 1 | File a bug; partial state preserved. |

Two invariants across all failure modes:

1. **The lockfile is always released on exit.** Implemented via `try` /
   `finally` around the entire run; signal handlers (`SIGINT`,
   `SIGTERM`) trigger the same cleanup.
2. **Partial run-branches stay on the local VM.** They are never deleted
   on failure. A failed run is forensic data.

**Stale-lockfile policy.** A lockfile contains the owning process PID
and the run start timestamp. The engine **does not auto-reclaim** stale
lockfiles in v1 — even if the recorded PID is dead, the next invocation
fails with the lockfile error and the recovery instruction is `rm
.a2sdlc/run.lock` after confirming no `a2sdlc` process is running. This
is a deliberately conservative choice: silent reclaim risks racing two
processes whose PIDs happened to recycle. Auto-reclaim with a TTL is a
candidate for a future spec; v1 keeps the behavior obvious.

## MLflow correlation

Every run logs to MLflow with:

- **`run_name`** = `workflow_id` (= run-branch name) — direct findability
- **Tags:**
  - `ticket_key` — when set
  - `base` — base branch name
  - `base_sha` — base commit SHA at run start
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
  ecosystem:    str             # = config.mode value
}
```

Future triggers (`github-webhook`, `jira-webhook`, custom event systems)
produce the same `StartWorkflow` shape with different sources. Engine
doesn't care which trigger fired.

## Migration notes

- Existing `state.json` consumers gain a `schema_version` check; v0 files
  (no `schema_version` field) are read into the v1 in-memory shape with
  `schema_version=0` and `ecosystem="local"` defaulted in. The migrated
  state is written back to disk **lazily**, on the next stage-finish
  commit — never eagerly on read. Migration is logged via the `console`
  subscriber as `state.migrated from=v0 to=v1` (grep-friendly,
  ASCII-only).
- `RunIntent.base` already carries the base branch — wire `base_sha`
  capture at workflow start.
- `format_branch` gains both directions of the mapping for the local
  ecosystem: existing `format_branch(ticket_key)` for the GH ecosystem
  stays; new `format_run_branch(base, ts, input_hash) -> str`
  *generates* the local run-branch name (argument order matches the
  rendered name `<base-slug>/<ts>-<input-hash>`), and a paired
  `parse_run_branch(branch) -> (base, ts, input_hash) | None`
  *extracts* the components for telemetry and queries.
- The `merge` stage is removed from the v1 default pipeline (still exists
  in code; just not in the local-mode stage list).

## Acceptance criteria

1. A fresh repo with `INPUT.md` on a `req/*` branch and a minimal
   `.a2sdlc/config.yaml` runs end-to-end via `a2sdlc run` on a VM,
   produces a run branch on origin, and writes all per-stage artifacts
   under `.a2sdlc/state/<branch>/`: `spec.md`, one or more
   `implement-cycle-<n>.md`, and review files under `reviews/`. Prints
   the run-branch name on stdout.
2. Re-running with the same `INPUT.md` produces a branch with the same
   hash suffix (different timestamp); BA can detect duplicates.
3. Re-running after editing `INPUT.md` produces a branch with a different
   hash suffix.
4. Removing a required env var causes the CLI to exit non-zero in
   sub-second time, listing every missing var by name and which adapter
   needs it.
5. MLflow shows the run with `run_name = <branch-name>` and pivotable
   tags (`ticket_key`, `base`, etc.).
6. Review handover loop fires at least once when the SPEC stage's
   output requires changes, visible as `REVIEW → IMPLEMENT` transitions
   in stdout and as multiple `<ts>-cycle-<n>.md` files in the review
   folder.
7. Engine refuses to run on a protected base (`main`) without an
   explicit `--allow-protected-base` flag.
8. Architecture tests still pass — domain has zero a2sdlc imports;
   composition root remains the only 5+-package importer.
9. Concurrent invocation: starting a second `a2sdlc run` while a first
   is still active fails fast with the lockfile error from §Failure
   modes; the lockfile is removed on first run's exit.
10. Dirty working tree: an uncommitted change to a tracked file causes
    the run to fail with the dirty-tree error before any branch is
    created.
11. v0 `state.json` migration: a fixture state file without
    `schema_version` is accepted on read, surfaces a `state.migrated
    from=v0 to=v1` log line, and is rewritten on the next
    stage-finish commit (not eagerly) with `schema_version=1` plus
    every other v1-mandated identity field present (`workflow_id`,
    `ticket_key` semantics, `base`, `base_sha`, `ecosystem`).
12. Per-stage stats summary line is printed at every stage terminal
    transition (`done` / `handover` / `approved`) with all five fields
    (duration, turns, tokens-in, tokens-out, cost), and a final
    `totals:` line aggregates across all stage runs.
13. Console cadence: each stage prints exactly one `starting (cycle N)`
    line **per stage entry** (cycles re-print on re-entry of IMPLEMENT
    or REVIEW), every progress event (including tool calls) inline
    with no throttling, an `===== a2sdlc:stage-output BEGIN =====` /
    `===== a2sdlc:stage-output END =====` block carrying the stage's
    primary artifact (SPEC → `spec.md`, IMPLEMENT →
    `implement-cycle-<n>.md`, REVIEW → `reviews/<ts>-cycle-<n>.md`
    plus the paired inline file when present), and one terminal stats
    line. The block content is byte-equal to the file the active
    adapter wrote.
14. `RunEnd` fires on **both success and failure** paths. On success
    the console prints `totals: <stats>`; on failure (any exit path
    in §Failure modes that occurs after at least one stage ran) the
    console prints `totals (failed): <stats>` followed by the failure
    error message. The `aggregate_stats` cover whatever stages
    actually ran.
15. **End-to-end smoke test against a real scratch repo.** A make
    target (`make smoke-local`) implements the harness specified in
    §Testing strategy → "End-to-end smoke" — see that section for
    the full step list and cleanup policy. AC #15 specifically
    requires: the run-branch exists locally **and** on the local
    origin; all expected artifacts are present (`spec.md`, ≥1
    `implement-cycle-<n>.md`, ≥1 review file under `reviews/`); the
    stdout transcript contains the
    `===== a2sdlc:stage-output BEGIN =====` / `END =====` fences and
    a `totals:` line; exit code is 0; **and** when required env vars
    are absent the target exits 0 with the banner line
    `smoke-local skipped: <VAR> not set`.

## Testing strategy

Three tiers; the implementation plan must include all three.

### Unit tests
Per-module, fast, no I/O. Cover: branch-name generation +
parsing (round-trip), env-var validator, dirty-tree check, lockfile
acquire/release + signal handler, state-blob v0→v1 migrator, stats
formatters (the `_format_*` helpers), `RunEnd` aggregation across
mock stage runs, output-block fence rendering.

### Integration tests
Use `LocalFileWorkAdapter` + `LocalReviewAdapter` against a temporary
git repo (pytest fixture) with mocked agent calls. Assert: artifact
files land at the spec'd paths; `state.json` schema_version is set;
re-run with same INPUT.md produces same hash suffix; protected-base
guard fires; lockfile error fires on concurrent invocation.

### End-to-end smoke (real `a2sdlc run`)
A `make smoke-local` target performs a *real* run end-to-end against
a scratch repo created inside the harness. **Scope: happy path only.**
Failure-mode coverage (the 10-row §Failure modes table) lives in the
unit + integration tiers — adding a smoke variant per failure mode is
explicitly out of scope and would blow the appetite. Each row in
§Failure modes maps to one integration-test case.

Steps:

1. Creates `tmp/smoke-local/repo/` (cleaned at start), `git init`s it,
   initializes a "local origin" via a bare repo at
   `tmp/smoke-local/origin.git/` and sets it as `origin` remote on
   the working repo.
2. Creates a base branch `req/smoke-feature` carrying a tiny
   `INPUT.md` (a deliberately small change request, e.g. "add a
   `greet()` function returning `'hello, <name>!'` and a unit test")
   plus a minimal `.a2sdlc/config.yaml` pointing at the local
   ecosystem.
3. Commits + pushes the base to the local origin.
4. Invokes `a2sdlc run` from inside the working repo with the
   required env vars set from CI secrets. **If a required env var is
   absent, the target exits 0 with a single banner line:
   `smoke-local skipped: <VAR> not set`** — grep-able in CI logs but
   not a hard failure (smoke is opt-in when keys aren't available).
5. Captures stdout to a file; asserts (matches AC #15 exactly):
   - exit code 0
   - the run-branch exists locally **and** on the local origin
   - per-stage artifacts are present at the spec'd paths
     (`spec.md`, ≥1 `implement-cycle-<n>.md`, ≥1 review file under
     `reviews/`)
   - stdout contains the `===== a2sdlc:stage-output BEGIN =====` /
     `END =====` fences and a `totals:` line
   - the run-branch's tip commit on origin contains the
     agent-produced changes
6. Tears down `tmp/smoke-local/` on success. **On failure**, the
   harness preserves the entire directory under
   `tmp/smoke-local-failed-<ts>/`. **Cleanup policy: only the most
   recent failed run is preserved.** The harness deletes any older
   `tmp/smoke-local-failed-*` directories at the start of each run,
   bounded retention regardless of CI cadence.

`tmp/` must be in the repo's `.gitignore` so the harness doesn't
collide with the dirty-tree check from CLI step 4. Adding the
`.gitignore` entry is part of the implementation plan.

This is the spec's primary trust surface — unit and integration tests
prove the wiring; the smoke proves the engine actually does the job.
The implementation plan must produce the harness, the
`make smoke-local` target, and a CI job that runs it (gated on the
required env vars being present, exits 0 with the banner when not).

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
