# Mode 2 UX Audit — Running Notes

Scratch pad during the test/fix loop kicked off 2026-04-21 post-initial-smoke.
Promoted to a proper handover when the session ends.

## Scenarios

| # | Issue | Shape | Status |
|---|---|---|---|
| #1 | Patient intake CLI | Greenfield scaffold | merged (prior smoke) |
| #2 | `--format json` flag | Extend existing code | in flight |
| #3 | Bugfix (planned) | Fix-in-existing-code | pending |
| #4 | Ambiguous/minimal spec (planned) | Probe spec-stage clarification | pending |

## Observations — Ticket #2 (extend-existing)

### Good

- Label→workflow trigger latency: sub-15s.
- Spec stage completed cleanly in ~6min with a finalized `✅` comment; no mid-stage thrash.
- Concurrency group correctly cancelled the duplicate `issue_comment` run fired by the engine's own ✅ comment (bot-filter + concurrency working together).
- Stage-transition to `stage:implement` routed cleanly into implement stage.
- Live-updating comment during stage shows tool timeline — excellent visibility.

### Confirmed bugs (fixes landed this session)

- `agent` trigger label lingered alongside `stage:implement` after pickup — fixed in `set_stage_label` (also strips `agent`).
- `create_draft_pr` would 422 on retry if an open PR already existed — fixed via `get_pulls(head=owner:branch)` reuse guard.
- JSON log formatter dropped `extra={...}` kwargs — replaced with `_JsonFormatter` that serializes all non-standard LogRecord attrs.

### Open observations (not yet fixed)

- "Agent" row in the live-comment tool timeline shows an empty target column — minor; subagent dispatches don't have a single file/target.
- Second `issues` workflow run fires when engine sets `stage:*` label (this is the state machine re-entering). Still looking for whether this causes thrash on #2 or is handled cleanly by the pipeline's internal state check.

## Observations — Ticket #8 (new subcommand — `search`)

### Critical bug found + fixed

**Per-ticket state leaked into base branch.** Engine MERGE stage for #8 logged
`dispatch.merged pr=7` — merging the previous ticket's PR number instead of #9
(the actual PR for #8). Chain:

- Ticket #2's branch had `.a2sdlc/state.json` (pr_number=7).
- Squash-merge into main carried it over.
- Agent/8 branch was checked out from main with `state.json` (pr_number=7) inherited.
- SPEC stage on #8 read state → pr_number=7 (NOT None) → skipped `create_draft_pr`. But my earlier fix also checks for open PRs by branch; agent/8 had none, so it created PR #9 and that pr_number stuck on subsequent stages.
- However MERGE stage — with gate=AUTO — read state again and the stale pr_number=7 took precedence somehow (still digging into exactly which read). Engine called `pull.merge(7)` on the already-merged #7, GitHub treated it as a no-op, engine logged "merged" and set `stage:done`. Issue closed on PR #7 linkage long before; label state ended up inconsistent.

**Fixes pushed:**
- `_commit_and_push` now commits only `.a2sdlc/state.json` + `docs/`, not the whole `.a2sdlc/` dir. Logs stay on the runner working tree.
- New `GitAdapter.strip_runtime()` contract removes `state.json`, `logs/`, `handover/` from the branch and commits the deletion right before squash-merge. Base never sees runtime artifacts.
- Main branch cleaned manually (removed leaked `state.json` + 9 log files).

### Also confirmed

- **Self-approval still blocks on APPROVE**: post_review falls back to PR issue comment (noisy, duplicates the stage-side comment). Follow-up #1 remains open.
- **Concurrency group working**: all `issue_comment` trigger runs were cancelled cleanly while `issues` runs queued.
- **Gate=AUTO end-to-end flowed through all 4 stages** (spec → implement → review → merge) once config was updated. So the state-machine transitions ARE correct; only the per-branch state hygiene was broken.

## Fixes landed this session

| # | Fix | Commit |
|---|---|---|
| 1 | JSON log formatter preserves `extra={...}` | 56cf481 |
| 2 | `create_draft_pr` reuses existing open PR instead of 422 | 3f046ca |
| 3 | `set_stage_label` strips `agent` trigger label too | 3f046ca |
| 4 | gitignore `mlflow.db` local dev artifact | d63a683 |
| 5 | `_parse_issues_event` skip closed issues (superseded) | 0871786 |
| 6 | Engine-level `WorkAdapter.is_ticket_active` contract | 026afd4 |
| 7 | Strip `.a2sdlc/{state,logs,handover}` before merge; narrow commit paths | 24abaf8 |

## Still-open follow-ups

- **Reviewer identity (self-approval 422)** — original #1. Decide between option (a) second reviewer App, (b) service PAT, (c) skip GH Review API entirely in Mode 2 and rely on stage comment.
- **Mode 2 idempotency** — `ctx.run_id` still None in Mode 2; `check_idempotency` inert. Duplicate re-deliveries could still re-run stages.
- **State.json-as-source-of-truth (flip contract)** — broader refactor; separate from the hygiene fix above.
- **Engine token sniff** — reject `ghs_`-prefixed GITHUB_TOKEN with a clear error.
- **`issues:closed` action should also trigger engine cleanup** — set stage:done, strip labels, stop any in-flight runs.
- **Inconsistent PR-side messaging on APPROVE self-review** — fallback `create_issue_comment` on PR duplicates the stage comment. Either suppress (trust stage comment) or de-duplicate.
