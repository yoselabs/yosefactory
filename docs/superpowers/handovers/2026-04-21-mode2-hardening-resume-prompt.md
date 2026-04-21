# Resume Prompt — Mode 2 Hardening Continuation

> **Paste this verbatim into a fresh session to pick up the work.** Assumes the new agent has no prior context.

---

## Where we are

You're picking up after a Mode 2 hardening session on `yoselabs/a2sdlc`
branch `feat/mode2-smoke-telemetry`. A previous session shipped the
initial telemetry rewiring + a full smoke test; this session added 16
commits covering idempotency, state hygiene, error UX, and a
tracker-agnostic WorkAdapter direction.

End-to-end automation is **verified working** — ticket `iorlas/a2sdlc-smoke#10`
flowed spec → implement → review → merge → done with no manual steps on
the final pass. `make check` is green; 542 tests pass.

**Required reads before doing anything (in order):**

1. `docs/superpowers/handovers/2026-04-21-mode2-hardening-handover.md` — this session's outcome summary.
2. `docs/superpowers/handovers/2026-04-21-mode2-followups.md` — prioritized P0/P1/P2 list with decisions captured.
3. `docs/superpowers/handovers/2026-04-21-mode2-smoke-handover.md` — the previous session's work (context for why things exist).

Do not re-do any work already in the "What changed this session" table.

## Environment facts (do not re-discover)

- Engine repo: `yoselabs/a2sdlc`, package at `packages/engine/`.
- Smoke repo: `iorlas/a2sdlc-smoke` — main is clean (`.a2sdlc/config.yaml` only).
- Smoke secrets already configured: `A2SDLC_APP_ID`, `A2SDLC_APP_PRIVATE_KEY`, `A2SDLC_INSTALLATION_ID`, `CLAUDE_CODE_OAUTH_TOKEN`, `MLFLOW_*`.
- Smoke config has `gates.merge: auto` — engine auto-merges on APPROVE verdict.
- Smoke workflow still pinned to `@feat/mode2-smoke-telemetry`; reset to `@main` on merge.
- 542 tests pass under xdist in ~30s. `make check` is the full gate.

## Decisions already settled (don't re-litigate)

1. **Reviewer identity → CLOSED.** No PAT, no second App. Engine APPROVE self-review 422 is silently skipped; humans approve via native GH UI; `check_human_approval` reads non-bot approvals; REQUEST_CHANGES self-reviews work fine. The issue-side stage comment carries the engine's verdict.

2. **`stage:done` label → DROPPED.** Native issue-closed state is the done signal. `set_done_label` closes the issue + strips `stage:*` + `agent` labels, does NOT add `stage:done`. Matches Jira's "Done" status semantics.

3. **Concurrency → KEEP QUEUE.** `cancel-in-progress: false`. Idempotency (via `ctx.run_id`) makes stale events cheap. Cancel-in-progress would create orphan "⏳ in progress" comments.

4. **WorkAdapter protocol refactor → STARTED.** `get_current_stage` added as the first additive slice. Full rename + pipeline-ledger relocation is the next chunk.

## Next-priority work

### 1. Full WorkAdapter rename (P0)

Rename these methods across protocol, GH impl, LocalFile impl, WorkflowInput
impl, FakeWorkAdapter, and all callers:

- `set_stage_label` → `set_current_stage`
- `set_blocked` → `mark_blocked`
- `set_done_label` → `mark_done`

Mechanical but touches many files. No behavior change. After this,
`WorkAdapter` is fully tracker-agnostic in naming and ready for a Jira
implementation.

### 2. Pipeline ledger off the ticket branch (P0, Phase-2 blocker)

Today `.a2sdlc/state.json` lives on the ticket branch and is cleaned up
from base post-merge. Jira has no branch concept, so this needs to be
tracker-storage-agnostic.

Target: `StateManager` accepts a pluggable storage backend.

- **GitHub backend:** orphan ref like `refs/a2sdlc/state/{ticket_key}`. Never merged. Fetched per stage. Survives branch delete.
- **Jira/dispatcher backend:** RPC to the dispatcher's KV.

Start by adding a `StateStorage` protocol with `read(key) -> str | None` and `write(key, data)`. Refactor `StateManager` to take a `StateStorage` and pass through.

### 3. `cleanup_base` push-rebase retry (P0, tactical)

~10 LOC. When two tickets merge concurrently, both call `cleanup_base`
on the same base branch. One push succeeds; the other rejects with
non-fast-forward. Currently we log a warning and move on. Retry once
with `git pull --rebase` handles the typical race.

### 4. Consumer onboarding doc (P1)

One-pager covering:

- Required secrets (`A2SDLC_APP_ID`, `A2SDLC_APP_PRIVATE_KEY`, `A2SDLC_INSTALLATION_ID`, `CLAUDE_CODE_OAUTH_TOKEN`, `MLFLOW_*`).
- `gates` config tradeoffs (HUMAN vs AUTO merge).
- Minimum `a2sdlc-run.yml` workflow (include `closed` in `issues: types` for the new close-handler).
- App install + permission list.
- How the engine behaves under each gate mode.

### 5. MLflow `session_id` for parallel A/B runs (P2)

Already documented in TODO. Derive session_id from `run_id` to prevent
parent-run collisions when running the same ticket twice with different
prompts.

## Do not do

- Don't switch reviewer identity to a PAT or second App — decision CLOSED.
- Don't add `stage:done` back — native closed state is the signal.
- Don't flip concurrency to `cancel-in-progress: true` — idempotency handles stale events.
- Don't run another smoke on `#10` — it's merged and verified.
- Don't skip `make check` before declaring work complete.

## If you need to run a new smoke

```bash
# Pick a scenario NOT yet exercised (see followups doc "Scenarios not yet tested"):
#  - concurrent tickets on different issues
#  - human PR review comment → IMPLEMENT re-run
#  - circuit breaker firing (≥ max review cycles)
#  - ambiguous ticket → SPEC QUESTIONS
#  - stage-override directives (base:, gate_spec: in ticket body)
#
# File an issue in iorlas/a2sdlc-smoke, label `agent`.
gh issue create --repo iorlas/a2sdlc-smoke --title "..." --body "..." --label agent
# Watch:
gh run list --repo iorlas/a2sdlc-smoke --limit 10
# Use a background waiter to avoid polling cost:
until [ "$(gh run list --repo iorlas/a2sdlc-smoke --limit 5 --json status --jq '[.[] | select(.status == "in_progress" or .status == "pending" or .status == "queued")] | length')" = "0" ]; do sleep 30; done
```

Expect end-to-end automation (spec → implement → review → merge → done)
on any clean ticket. Total cost per ticket: ~$2–3.

## Merge-to-main when ready

Steps in the handover doc. Reset workflow pins from
`@feat/mode2-smoke-telemetry` to `@main`. 150+ commits on the branch —
consider squash-grouping by theme rather than a single squash.
