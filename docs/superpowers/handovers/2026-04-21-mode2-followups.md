# Mode 2 Hardening — Follow-ups After 2026-04-21 Smoke

Written after 11 fixes landed + end-to-end verification on `iorlas/a2sdlc-smoke` ticket #10.
Priority shorthand: **P0** = blocks Phase 2 / data loss risk, **P1** = correctness
gap that will bite soon, **P2** = UX / polish.

## P0 — Correctness & architecture

### P0.1 · Mode 2 engine-level idempotency

**Problem.** `cli/dispatch.py` Mode 2 branch doesn't populate
`DispatchContext.run_id`. `StateManager.check_idempotency` returns early with
`False`. Result: every triggering event (label change, comment, re-delivery)
re-runs the whole stage, even if the previous run finished. The
GHA-level `concurrency:` group serializes but doesn't dedupe.

**Why it matters.**
- Phase 2 (Jira dispatcher) relies on webhook delivery, and Jira redelivers
  aggressively on 5xx. Without idempotency the engine would burn cost on
  every redelivery.
- Even in Mode 2 today, the engine re-ran stages during ticket #8 when the
  state machine thrashed. Was only masked by state corruption preventing
  progress.

**Fix sketch.**
- Derive run_id deterministically: `f"{event.key}:{target_stage.value}:{git_head_sha}"`.
- `target_stage` is known by line ~144 in `dispatch()` — set `ctx.run_id`
  there, then `check_idempotency(ctx.run_id)` already works.
- Write `stage_run_id` into state on success.
- Test with two rapid label cycles on the same issue — only the first should
  execute.

**Size.** ~60 LOC + one pipeline test. No new architecture.

---

### P0.2 · Reviewer identity for APPROVE verdict

**Problem.** The App that authors PRs can't submit APPROVE reviews on its
own PRs — GitHub returns 422 "Review Can not approve your own pull request".
`post_review` catches this and falls back to `create_issue_comment`, which
(a) posts a duplicate of the stage comment on the PR, and (b) means the PR
has 0 actual approvals, so branch-protection rules that require
approvals would block auto-merge.

**Current mitigation (partial).** Smoke repo has no branch protection so
auto-merge succeeds; this session we also suppressed the APPROVE-422
duplicate comment. The 422 is no longer fatal but the PR carries no GH
approval artifact.

**Direction (settled 2026-04-21, decision #2).** PAT rejected — "no one
will be providing their personal access token." The engine's APPROVE
verdict via the Reviews API is actually **redundant**, and the current
post-4ec223b behavior is correct:

- `check_human_approval` filters out bot approvals by design. An engine
  APPROVE review would be ignored by the merge-gate check anyway, so
  posting it is pure cosmetics.
- REQUEST_CHANGES self-reviews **are allowed** by GitHub — the engine
  continues to use the Reviews API for that path. Feedback routing reads
  them and re-runs IMPLEMENT.
- Humans still review via the native GH UI. Their approvals are non-bot
  and count toward the merge gate.

**Net result:** we already have what we wanted. The 422 on engine APPROVE
is silently skipped (commit 4ec223b); the issue-side stage comment
carries the engine's verdict for humans to see. No separate App, no PAT.

**Jira parity note.** In Mode 1 (dispatcher), no post_review API call is
made at all — the engine's verdict transitions the Jira ticket via the
dispatcher RPC. GitHubReviewAdapter stays GH-specific.

**Status:** CLOSED. No further work needed here.

---

### P0.3 · Concurrency & state storage

**Direction shift (2026-04-21).** The user raised a simpler question:
why allow concurrent runs on the same ticket at all? Two runs both
trying to produce the same spec would just overwrite each other. Prevent
the concurrency and most of this problem disappears.

**Concurrency semantics — three options.**
- **(X) Single-flight per ticket, coalesce newer events.** GHA
  `concurrency.cancel-in-progress: true` with a per-issue group. Newer
  events cancel queued ones (not in-flight ones). Fix-retries work
  because they arrive as new events after the old one was cancelled.
- **(Y) Single-flight per ticket, queue newer events.** Current
  behavior — `cancel-in-progress: false`. Safer (no cancelled work) but
  lets stale events fire after resolution, which is the thrash path
  from this smoke.
- **(Z) Single-flight per ticket + engine-side event-coalescing.**
  Engine checks "is there a newer event queued for this ticket?" at
  entry and skips. Requires queue visibility GHA doesn't give us
  directly.

**Direction (settled 2026-04-21, decision #3).** Keep queue, DON'T flip
to cancel-in-progress. Rationale:

- Idempotency (P0.1, landed) makes stale events cheap: ~10s of runner
  infra per duplicate, no AI cost. The thrash path from the original
  smoke is already neutralized.
- Cancelling a mid-flight stage leaves an orphan "⏳ in progress"
  comment on the issue. There's no clean "cancel with cleanup" hook in
  GitHub Actions — we'd need an `always()` step that finalizes the
  comment, which is extra moving parts for marginal benefit.
- Fix-retries (human edits code, pushes new commit, re-labels) produce a
  new sha anyway, so the new run has a new run_id and runs legitimately
  even with the old one queued — no cancellation needed.

**Status:** Keeping queue semantics. If we later want orphan-comment
cleanup to enable safe cancellation, spec out the `always()` hook first.

**State-storage design — Jira parity framing.**

With the "no concurrent runs per ticket" assumption, the state-race
shrinks. Two tickets finishing MERGE on the same base can still race on
`cleanup_base` push — but that's a small, benign race (one warning log,
next merge cleans up).

The bigger issue is **tracker-agnostic state**. Today:
- GitHub: state.json on per-ticket branch + labels on issue.
- Jira: would need... what? Branches aren't a Jira concept. Labels
  don't exist the same way (Jira has status + custom fields).

**Clean abstraction.** Split what state.json holds today into:
1. **Stage position** — which stage is "current". Tracker-native: GH
   label, Jira status transition. Lives in the tracker.
2. **Pipeline ledger** — pr_number, review_cycles, accumulated cost,
   stage_run_id. Engine-internal bookkeeping, lives in engine-owned
   storage.

For (2), the right home is a **separate store keyed by ticket id**,
not branch-local. Options:
- Git notes on the tracker-repo (GH) or a separate metadata repo.
- A small KV in the dispatcher (Mode 1) — already has HTTP to Jira;
  can extend it with state RPC.
- For Mode 2: orphan branch `a2sdlc/state/{ticket_key}` — survives
  branch delete, doesn't pollute base, pulls per-stage.

Mode-1 runs through the dispatcher anyway — dispatcher-owned state is
natural. Mode-2 needs its own answer. Orphan branch is least magical
and works without a new service.

**Recommendation (architectural).** Plan a refactor where
`StateManager` accepts a pluggable storage backend; GitHub impl uses
orphan branch, Jira impl uses dispatcher KV. Current branch-local
state.json becomes the GitHub default implementation.

**Short-term mitigation for the cleanup_base race (tactical).** Detect
push rejection in `cleanup_base`; retry once with `git pull --rebase`.
~10 LOC.

---

### P0.4 · Tracker-agnostic state contract (Jira parity)

**Direction shift (2026-04-21).** The label/state-split question is
really "how does the engine talk to any tracker" — needs to work for
both GitHub labels and Jira status transitions. Solve once.

**The right abstraction.** `WorkAdapter` exposes two orthogonal APIs:

1. **Stage position** (read + write, tracker-native):
   - `get_current_stage(key) -> StageName | None` — reads the
     tracker-native stage marker (GH label / Jira status).
   - `set_current_stage(key, stage)` — writes it. Clears prior stage.
   - `mark_done(key)` — terminal. GH: close the issue + clear labels.
     Jira: transition to the done status.
   - `mark_blocked(key, reason)` — terminal-ish. GH: label + comment.
     Jira: custom status + comment.

2. **Pipeline ledger** (engine-internal, never tracker-visible):
   Lives in whatever P0.3 settles on (orphan branch for GH, dispatcher
   KV for Jira). Holds pr_number, review_cycles, accumulated cost,
   last stage_run_id.

**Concrete consequence for GitHub adapter.** `set_stage_label` becomes
`set_current_stage`; we already strip `agent` on transition. `stage:done`
vs issue-closed tension resolves: `mark_done` both closes the issue
(native "done" signal) AND strips stage:* labels. The `stage:done`
label becomes redundant — cleaner to just rely on the issue state. (This
also means Jira parity is easier: Jira's "Done" status is the analog of
GH's "closed state".)

**Landed 2026-04-21 (decision #2).** `set_done_label` no longer adds
`stage:done`. Instead it:
- Strips all `stage:*` and `agent` labels.
- Closes the issue if not already closed.

The done signal is now the native closed-state, matching Jira's "Done"
status semantics. DONE_LABEL constant is kept but unused (can remove
when the broader rename PR lands).

**Additive step landed 2026-04-21.** `WorkAdapter.get_current_stage(key)`
added to the protocol; GH reads the `stage:*` label, Jira (future) reads
the status. This is the first piece of the stage-position abstraction.

**Rename landed 2026-04-21.** `set_stage_label` → `set_current_stage`,
`set_blocked` → `mark_blocked`, `set_done_label` → `mark_done` across
protocol, GH/LocalFile/WorkflowInput impls, FakeWorkAdapter, dispatch,
and all tests. 542 tests pass.

**StateStorage protocol landed 2026-04-21.** `StateManager` now takes a
`StateStorage` + ticket key. `GitFileStateStorage` wraps the current
file-on-branch behavior (the default). Paves the way for orphan-ref GH
backend (Phase 2) and dispatcher KV backend (Jira) without further
refactor to StateManager.

**Still to do:**
- Implement `OrphanRefStateStorage` using `refs/a2sdlc/state/{key}`.
  Needs smoke testing before landing — git plumbing for orphan refs
  (`git update-ref` + blob creation) isn't covered by existing tests.
- Move pipeline ledger (pr_number, review_cycles, cost) off the ticket
  branch: orphan branch for GH mode (`a2sdlc/state/{key}`), dispatcher KV
  for Jira mode. `StateManager` accepts a pluggable backend.
- `GitHubWorkAdapter` already has the building blocks; new `JiraWorkAdapter`
  arrives with Phase 2.

---

### P0.5 · Error UX — issue comment pointer, traceback stays in CI ✅

**Direction shift (2026-04-21).** User wants to keep full traceback in
CI logs — useful for debugging. Just needs a short pointer on the issue.

**Landed this session (commit 4ec223b).** `cli/dispatch.py` now wraps
`asyncio.run(dispatch(ctx))` in a try/except that:
- Logs the full traceback in CI (unchanged — ops can still dig in).
- Calls `set_blocked` with `Stage failed: <exc> — see run: <gh-actions-url>`.
- Preserves the Typer exit code so CI marks the run failed.

`set_blocked` itself is now idempotent, so retries don't stack duplicate
"Blocked:" comments on the issue.

**Still open.** The blocked-comment points to the Actions run, not the
specific failing step. A future polish could extract the stage name
(already available as a label) and include it in the message.

---

## P1 — Correctness gaps (most fixed this session)

### P1.1 · Engine-side token sniff ✅

Landed in commit 4ec223b. `cli/dispatch.py` refuses to run with a
`ghs_`-prefixed `GITHUB_TOKEN` and tells the user to configure the
GitHub App instead.

---

### P1.2 · `issues:closed` triggers engine cleanup ✅

Landed in commit 4ec223b. `_parse_issues_event` emits a marker event
(`is_closed=True`). Dispatch short-circuits to `set_done_label` + clear
stage:* without AI or branch work. Consumer workflows must list `closed`
in `issues: types:` — document this in the onboarding guide (P1.4).

**Open sub-question.** When the close was caused by the engine's own
MERGE (via "Closes #N" link), dispatch will re-enter with the close event
after the merge. Currently set_done_label runs twice (idempotent, fine)
but the code path duplicates work. Could gate with "already stage:done?
skip" at parse time.

---

### P1.3 · Duplicate PR comment on APPROVE self-review ✅

Landed in commit 4ec223b. Self-approval 422 is detected explicitly and
logged — no fallback comment. REQUEST_CHANGES self-reviews still post
(GitHub allows). Non-422 unexpected failures still fall back, but the
fallback is now deduplicated (scans existing PR comments first).

---

### P1.5 · Idempotency audit — further hardening landed

Broader scan this session found additional gaps beyond the dispatch-level
run_id guard:

- **`merge_pr` now checks `pull.merged` first** (commit 8ec7cf6 — about
  to land) — retries after a successful merge no longer crash with 405
  "already merged". Fixes a scenario where MERGE cleanup_base succeeded
  but a subsequent label/comment update failed and retried.
- **`set_blocked` dedupes "Blocked:" comments** by scanning the last 10
  comments — the "duplicate comments on issues" observation from the
  review is addressed.
- **`post_review` fallback is deduped** — on unexpected non-422 errors,
  scans existing PR issue comments for the "**Review: <verdict>**"
  marker before posting.

**Remaining from the scan (LOW severity):**
- `commit_empty` on SPEC retry could produce duplicate empty commits
  if SPEC runs twice without idempotency (harmless; git content-dedupes,
  but branch history noise).
- Telemetry `MlflowTelemetry.session` parallel-run race (already
  documented in TODO.md).

---

### P1.4 · `gates: {merge: auto}` is undocumented for consumers

**Problem.** Default `GateConfig.merge = HUMAN`. Smoke repo needed
manual `gates: {merge: auto}` in `.a2sdlc/config.yaml` for end-to-end
automation. There's no docs page telling consumers this, nor the
trade-off (AUTO skips branch-protection human approval checks — fine for
trusted internal repos, scary for open source).

**Fix.** Add a Mode 2 onboarding doc covering:
- config.yaml required fields
- gate mode trade-offs (HUMAN for production, AUTO for trusted-internal)
- required secrets (A2SDLC_APP_ID, A2SDLC_APP_PRIVATE_KEY, CLAUDE_CODE_OAUTH_TOKEN, MLFLOW_*)
- the App installation + permission list
- a minimum-viable `a2sdlc-run.yml` consumer workflow

**Size.** ~1 page of docs. Could be auto-generated from the config model.

---

### P1.6 · Decompose `pipeline/dispatch.py` into phase modules

**Problem.** `dispatch.py` hit the 500-line file-length limit twice in
the 2026-04-21 hardening session (rename commit, session_id commit).
Each fix needed to compress an unrelated comment block to make room.
The file mixes six phases that have natural seams:

1. Event parsing + directive resolution (SkipEvent, is_closed, base/gate
   overrides).
2. Idempotency + circuit-breaker guards (duplicate run_id, is_ticket_active,
   feedback_already_addressed).
3. Branch setup + state bootstrap (git.setup_branch, state read, feedback
   routing).
4. Telemetry/progress/comment wiring (session_id, telemetry.session,
   subscriber registration).
5. Stage execution (assembly, stage_executor, error classification).
6. Post-execution routing (next_stage, merge, cleanup_base,
   set_current_stage, mark_done).

**Fix sketch.** Split into `pipeline/preflight.py`, `pipeline/stage_run.py`,
`pipeline/post_stage.py`. Keep `dispatch.py` as the thin composition
root that wires them in order. Preserves the architecture rule that
"only pipeline/dispatch.py may import from 5+ a2sdlc packages" — the
new files can be phase-internal imports.

**Why it matters.**
- File-length pressure forces comment churn on every touch.
- Jira mode will add more branching in phases 1 + 3. Harder in a 500-line
  file.
- Unit tests can target phases directly instead of mocking everything
  needed for full `dispatch()`.

**Size.** ~half-day refactor + regression smoke. Touches the main event
loop, so needs a live smoke on a clean ticket before landing.

**Blockers.** Should land alongside or after #2B (orphan-ref state
backend) to batch the smoke-requiring work.

---

## P2 — UX polish

### P2.1 · "Agent" row in tool timeline has empty target column

Observed in ticket #2/#8/#10 live comments. Subagent dispatches appear as
`| 3:18 | Agent |  |` — the target column is blank. Could show the
subagent's declared purpose (first word of its prompt, e.g. "review",
"research").

### P2.2 · Stage comments don't link to the PR

Issue comments say "✅ Merged" but don't link to the PR that merged.
Humans must scroll up to find the PR number. Similarly, PR lacks a
back-link to the originating issue beyond `Closes #N` in the body.

### P2.3 · `needs-input` / clarification label management

When SPEC returns `QUESTIONS` status, `next_stage` returns None and the
pipeline halts. But no label or comment tells humans what's expected.
Should set a `needs-input` label + post the questions as a bulleted
comment so humans know how to unblock.

### P2.4 · MLflow session_id collision on parallel A/B runs ✅

**Landed 2026-04-21 (387e54c).** `session_id = f"{event.key}:{ctx.run_id
or uuid4()}"` in `pipeline/dispatch.py`. GHA runs scope by run_id;
local runs get uuid4 so A/B locally also isolates. Claude SDK session
resumption still uses `get_session_id(ticket, stage)` (runner.py) —
deterministic-per-stage is correct for SDK resume.

### P2.5 · Circuit breaker for runaway cost per ticket

No hard ceiling on accumulated spend per ticket. The existing review-cycle
circuit breaker only catches loops in REVIEW stage. An implementation
that keeps asking follow-up questions in SPEC could burn unbounded cost.
Add `max_cost_usd_per_ticket` config (default $10? $25?); if
`state.accumulated_cost_usd` exceeds, block stage with a clear comment.

---

## Ship-critical for Phase 2 (Jira dispatcher)

Before flipping the switch to Jira + real tickets:

1. **P0.1 (idempotency)** — hard requirement; webhook redelivery is
   guaranteed to happen.
2. **P0.2 option (c)** — Jira has no PR-review API at all; reuse the
   "engine verdict = decision" path.
3. **P0.3 (state storage)** — either the rebase-retry band-aid or the
   orphan branch. No "base branch" concept in Jira means state on branch
   tied to git is already half-wrong for the Jira world.
4. **P1.1 (token sniff)** — Jira dispatcher mode still uses GitHub for
   PR lifecycle; same failure mode applies.
5. **P0.5 (error UX)** — Jira tickets shouldn't silently stall. Post a
   comment + set a status on every engine failure.

Everything else is polish that can land post-Phase-2.

## Scenarios not yet tested

- **Concurrent tickets.** Two `agent`-labeled issues submitted within
  seconds. Today's `concurrency:` group is per-issue — two different
  issues run in parallel. State writes race? cleanup_base races?
- **Feedback loop.** Human posts a comment on the PR requesting changes.
  Engine should route to IMPLEMENT stage with the feedback. We wired this
  up but haven't exercised it.
- **Circuit breaker firing.** Force REVIEW → IMPLEMENT → REVIEW ≥ max_cycles
  to confirm the breaker triggers and blocks cleanly.
- **Mid-stage runner death.** Kill the runner mid-implement; confirm the
  next run picks up correctly. Depends on P0.1 landing first.
- **Ambiguous spec.** Ticket with deliberately vague acceptance criteria —
  does SPEC ask questions? Does it halt with `needs-input` UX (P2.3)?
- **Stage override via directive.** `base: develop` / `gate_spec: human`
  in the ticket body — need a smoke to confirm directives actually wire
  through.

## Items to prune from the live TODO

These TODO.md entries are done and can be removed:

- Entire "Logging" section (fixed in 56cf481).
- "Mode 2 auth/trigger follow-ups → `agent` label lingers" (fixed in
  3f046ca).
- "Mode 2 auth/trigger follow-ups → Existing-PR reuse" (fixed in 3f046ca).
