# Resume Prompt — Mode 2 Architecture Continuation

> **Paste this verbatim into a fresh session.** Assumes the agent has
> no prior context.

---

## Where we are

You're picking up after a Mode 2 architecture session on
`yoselabs/a2sdlc`. The earlier hardening branch has merged to `main`
(`main` @ `9eec45f`, 18 session commits). Four latent runtime bugs
caught and fixed live. Architecture now has clearer lines:
runtime-state in a single folder, pre-merge strip on feature branches,
engine owns all external integrations.

**Required reads before doing anything (in order):**

1. `docs/superpowers/handovers/2026-04-21-mode2-architecture-handover.md`
   — this session's outcome + decisions + don'ts.
2. `docs/superpowers/handovers/2026-04-21-mode2-followups.md` — live
   priority list with ✅ marks on landed items.
3. `~/Documents/Knowledge/Evolution/signals/2026-04-21-2341-unit-tests-miss-gh-token-auth-bugs.yaml`
   — the session's learned pattern about testing gaps.

Do not re-do any ✅ item.

## Environment facts (do not re-discover)

- Engine repo: `yoselabs/a2sdlc`, package at `packages/engine/`.
- Smoke repo: `iorlas/a2sdlc-smoke` — workflow pinned `@main`,
  issues trigger includes `closed`, secrets configured.
- Engine-install workflow pins point at `@main` — no branch pinning.
- Smoke config: `gates: {merge: auto}`, `self_answer: true` (implicit
  or explicit — check `.a2sdlc/config.yaml` if verifying QUESTIONS).
- 599 tests pass; `make lint` + `ty` clean.
- `make check` coverage-diff fails pre-existingly (branch churn vs main
  before merge) — not a regression.

## Decisions already settled (don't re-litigate)

1. **Runtime folder.** All runtime artifacts live under `.a2sdlc/state/`.
   Strip operation = `rm -rf .a2sdlc/state/` (opaque bag).
2. **Pre-merge strip.** `strip_runtime_state()` runs on the feature
   branch before `pr_lifecycle.merge()`. Engine never pushes directly
   to base. Works under branch protection.
3. **Engine owns integrations.** Agent does code only. All tracker/VCS
   operations route through adapters. PR title update happens in-engine
   at merge time via `work.get_ticket_title(key)` +
   `review.update_pr_title(pr_number, title)`.
4. **#2B narrows to Jira-only.** GH mode no longer needs orphan-ref.
5. **`ghs_` token-prefix sniff is WRONG.** Both App installation tokens
   and GHA default share the prefix. See P2.6b for the sound approach.

## Next-priority work

### 1. P1.6 · Decompose `pipeline/dispatch.py` (P0, half-day)

Hit the 500-line limit five times this session. Natural seams:

- `pipeline/preflight.py` — event parsing, directives, is_closed,
  is_active, idempotency check.
- `pipeline/stage_run.py` — assembly, prompt, stage_executor, result.
- `pipeline/post_stage.py` — transition, next_stage, set_current_stage,
  mark_needs_input, mark_done.
- `pipeline/merge_flow.py` — strip, title update, merge, finalize.
- `dispatch.py` stays as thin composition root.

Needs its own smoke. Biggest remaining structural work.

### 2. Integration-test tier for GH adapter (P1, ~half-day)

From the reflect signal. Two session bugs (ghs_ sniff, get_app probe)
passed unit tests under mocks, failed first live smoke. Add a
`pytest-vcr` or equivalent fixture tier:

- Record a real installation-token session against the smoke repo.
- Replay deterministically in CI.
- Any PR touching `adapters/work/github.py` or
  `adapters/review/github.py` must cross it.

Pays for itself on the next auth bug.

### 3. P2.6b · Sound token probe (P2, ~30 LOC)

Replace the reserved `expected_app_id` arg in
`GitHubWorkAdapter.from_token` with a probe using an installation-token-
compatible endpoint. Candidates:
- `GET /installation/repositories`
- Raw `requests` call with `Authorization: Bearer <token>` +
  response-shape check.

Mismatched app_id → raise ValueError with a pointer at
`actions/create-github-app-token@v3`.

### 4. Smoke untested paths (P1, needs smoke budget)

1. **QUESTIONS path** — set `self_answer: false` in smoke config, file
   a deliberately ambiguous ticket, verify `needs-input` label lands
   and `proceed` label clears it on next run.
2. **Feedback loop** — post a PR review comment requesting changes,
   verify engine routes to IMPLEMENT with the feedback.
3. **Circuit breakers** — force review-cycle breaker (artificial
   CHANGES_REQUESTED loop) or cost breaker (lower ceiling via
   `max_cost_usd_per_ticket: 1.0` in config).
4. **Stage-override directives** — ticket body with `base: develop`
   and/or `gate_spec: auto`.

### 5. Agent-tool audit (P2, defer unless Jira prep)

Engine now overwrites PR title at merge, so agent's residual ability
to call `gh pr edit` is cosmetic. But for Jira/multi-tracker mode,
tightening `allowed_tools` to exclude tracker-specific shell commands
prevents divergence. Optional before Jira phase.

## Do not do

- Don't re-add the `ghs_` prefix token sniff. See P2.6b for the sound
  approach.
- Don't write `cleanup_base` back. Direct push to base fails under
  branch protection.
- Don't move state back to flat `.a2sdlc/state.json`. Folder-as-bag
  is the design.
- Don't add agent-side GH/Jira integration tools. Adapters own
  integrations.
- Don't use `git add -A` — sweeps untracked user work. Use `git add -u`
  or explicit paths.
- Don't skip `make check` before declaring work complete.
- Don't re-run a smoke on tickets already merged (#12, #14, #16, #18).

## How to kick a new smoke

```bash
# Pick a scenario from the "untested paths" list. Examples:

# Happy path (regression check):
gh issue create --repo iorlas/a2sdlc-smoke \
  --title "Add a short helper for X" \
  --body "..." --label agent

# QUESTIONS test (requires self_answer: false in smoke config):
gh issue create --repo iorlas/a2sdlc-smoke \
  --title "Figure something out" \
  --body "Make things better somehow" --label agent

# Watch:
gh run list --repo iorlas/a2sdlc-smoke --limit 5

# Background wait:
until [ "$(gh run list --repo iorlas/a2sdlc-smoke --limit 5 --json status \
  --jq '[.[] | select(.status == "in_progress" or .status == "pending" or .status == "queued")] | length')" = "0" ]; do sleep 30; done
```

End-to-end happy path: ~5–15 min, ~$2–4 per ticket.

## Post-merge verification checklist

After any smoke that reaches MERGE, verify:

1. Issue closed (`gh issue view N --repo iorlas/a2sdlc-smoke --json state`).
2. No lingering labels (expect `[]`).
3. PR merged with descriptive title (not `agent/N`).
4. Main's `.a2sdlc/` contains ONLY `config.yaml` (no `state/` leaked).
5. Feature branch's HEAD~1 (pre-strip) has `.a2sdlc/state/state.json`
   for debug history.
