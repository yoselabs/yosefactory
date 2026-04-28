# Resume Prompt — engine bugfix followups (post-V1.0)

> Paste verbatim into a fresh session. Two-day arc on engine quality + phase-1 of gates-via-labels.

---

## Where we are

V1.0 migration (P1–P8) shipped 2026-04-23. Since then the focus has been hardening the engine against bugs surfaced in live smokes and starting the gates-via-labels migration. `main` is clean, `make check` green throughout.

### What landed (most recent first)

Engine bugfixes — caught and verified via real smoke runs against `iorlas/a2sdlc-smoke`:

- `e871e9d` — **`_ensure_draft_pr` branch-match guard**. Manual merges (e.g. CLI `gh pr merge` when the engine's MERGE-stage install step transient-fails) bypass `strip_runtime_state`, leaving `.a2sdlc/state/state.json` on the base branch. Next SPEC inherits the file, sees a stale `pr_number`, and skips creation. Fix: only trust `state.pr_number` when `state.branch == intent.branch`. 5 unit tests at `tests/pipeline/test_ensure_draft_pr.py`.
- `51b2851` — **`_get_pr_for_branch` head filter must use `owner:branch`**. PyGithub passes the `head` param verbatim to GitHub's API, which silently disables the filter when no owner is included. Cross-ticket contamination caught in smoke #42 — agent/42's REVIEW dispatch resolved PR #29 (a stale OPEN PR for agent/28). Defence-in-depth: also verify `pr.head.ref == branch` before accepting.
- `28d9a6c` + `0127e27` — **scenario-4 routing bugs.** Human APPROVE was being routed as IMPLEMENT feedback (`feedback_routing.py` ignored review verdict), and there was no path for "human APPROVE → AI merge" — manual merge was the only escape. Fixed by inspecting `review.state` in `_parse_pr_review_event` and emitting a proceed-shaped event for APPROVE so ingress's handover-based advance fires MERGE.
- `63b8604` — **SDK PreToolUse hook** that hard-denies `gh pr create/edit/merge/ready/close/reopen/review` (+ hub/glab equivalents). The SPEC agent was self-authoring `gh pr create` from its own plan, bypassing `_ensure_draft_pr`. Defence-in-depth alongside the prompt tightening in 9e4aeb3.

Refactor:

- `7d25cfb` — **stages drop pipeline-layer dep.** P8 follow-up. Moved `ExecutionResult` to `domain/`, added `RunContext.stage_executor` injected from `pipeline/dispatch.py`. Each stage now imports from 4 packages, off the cap-test EXEMPT list, retired four `ignore_imports` whitelist entries.

Gates via labels (Phase 1):

- `e993c13` — **label-form gate parser + ingress fresh re-read.** Mapping: `gate:merge:human` / `gate:merge:auto` / `gate:spec:human` / `gate:spec:auto`. `merge_directives(label_d, body_d)` — labels authoritative on conflict; bracket directives keep `base=` / `model=` (free-text) and act as fallback. `ingress.resolve_intent` calls `ctx.work.get_labels(event.key)` every dispatch. Validated end-to-end in smoke #47 (label-only ticket → REVIEW pause → APPROVE → AI merge).

### Smoke history this arc

| # | Outcome | Notes |
|---|---|---|
| #34 | ❌ wasted ~$1.50 | YAML directive form didn't parse — docs drift. |
| #36 | ✅ scenario 4 | Surfaced both routing bugs above. |
| #38 | ✅ scenario 6 | Surfaced SPEC-stage `gh pr create` leak. |
| #40 | ✅ scenario 4 retry | Validated APPROVE→MERGE end-to-end. |
| #42 | ❌ cross-ticket contamination | Found `_get_pr_for_branch` bug. |
| #43 | partial | First repro of `_ensure_draft_pr` no-PR pattern. |
| #44 | ✅ diagnostic confirms entry | Engine creates PR cleanly when state is fresh. |
| #46 | ❌ caught state leak red-handed | `state_branch=agent/44 / intent_branch=agent/46`. |
| #47 | ✅ label-form gate validated | Engine merged in 4s after APPROVE; state.json scrubbed. |

Total spend ~$15-18 across the arc. All bugs were live-only (unit tests didn't catch any).

## What's open

`TODO.md` is current. The actionable items (small → large):

1. **Auto-create the four `gate:*` labels** on first dispatch (or document the manual `gh label create` step). Today the labels exist on `iorlas/a2sdlc-smoke` because I created them by hand. New consumer repos would have label-form gates silently no-op.
2. **Update `docs/test_plan.md` scenarios 4 + 6** to recommend label form as the primary path; keep bracket form documented as fallback.
3. **Document the manual-merge gotcha** — strip_runtime_state runs only in the engine's MERGE stage. Anyone doing a manual `gh pr merge` (or click Merge in the UI) will leak `.a2sdlc/state/state.json` onto base. The branch-match guard makes this non-fatal but it's still leaked content.
4. **Detect base-branch state contamination at preflight** — if `.a2sdlc/state/state.json` exists on a freshly-checked-out base branch (i.e. `intent.state.branch != intent.branch`), log a warning. Or actively scrub it. Bigger semantic question: who owns base-branch hygiene?
5. **Diagnostic logs in `_ensure_draft_pr` are still INFO-level** (`302eabe`). Decide whether to demote to DEBUG now that the root cause is known, or keep them as a long-term observability surface.
6. **Older backlog items** in `TODO.md`: Progress comment redesign (I0239), Code review milestones, Review-stage context (it doesn't get the original ticket today), Pipeline features (`base:` body parsing edge cases, `auto_spec` prompt extraction, `proceed`-label state.json resume), GitLab/Jira adapters, etc. These are user-curated mid-term work, not urgent.

The engine itself is solid right now. If you want a fast win, items 1–3 are doc/quality and ~30 min each. Item 4 is a small but real engineering decision.

## Required reads before any tool call

1. `TODO.md` at repo root — the prioritized list with everything-shipped marked.
2. `docs/architecture.md` — layering rules. P8 contracts enforce them.
3. `docs/test_plan.md` — sentinel runs are up to date through smoke #47.
4. `git log --oneline -25` — confirm `main` matches what's documented above.

## Repo invariants (don't break)

- `make check` must stay green (it chains lint + test + test-integration + coverage-diff + security-audit).
- No GitHub PRs for this repo — Denis merges branches directly to `main` and pushes (`feedback_no_prs` memory).
- Pre-commit hooks reformat then abort on `ruff:format` failures. If a commit silently doesn't land, re-stage and retry. Never `--no-verify`.
- Cassette tier (`tests/integration/adapters/cassettes/`) is live. Recorded against an installation token from `iorlas/a2sdlc-smoke`'s App. To re-record: see `docs/superpowers/handovers/2026-04-23-p8-kickoff-resume-prompt.md` for the mint-token workflow.
- Diff-coverage gate is on; every changed line needs coverage.

## Smoke etiquette

- Engine pulls from `yoselabs/a2sdlc@main` at workflow trigger time. Push to main → next dispatch uses fresh engine code.
- Each smoke run on `iorlas/a2sdlc-smoke` costs real Claude API money (~$0.50–$3 depending on ticket complexity). Always close the issue at the end if a smoke is exploratory; the engine won't auto-cleanup if the pipeline gets stuck.
- Stale OPEN PRs / branches from earlier smokes can confuse adapters even with fixes (we saw this in smoke #42). When in doubt, `gh pr list --state open --repo iorlas/a2sdlc-smoke` and close anything older than the previous successful merge.

## Suggested first move

If you want progress on the gates-via-labels migration:

1. Add an engine startup-time helper to `adapters/work/github.py` that ensures the four `gate:*` labels exist (idempotent — list, then `create_label` for missing ones). Wire it into the first SPEC dispatch on a repo, gated by an env var so it doesn't fire on every run.
2. Update `docs/test_plan.md` §4 and §6 ticket shapes to use label form by default.
3. Run a smoke that exercises the new auto-create path on a fresh test repo (cheap — a single SPEC, not a full pipeline).

If you want quality plumbing:

1. Demote `dispatch.ensure_draft_pr.entry` / `.creating` to DEBUG (or wrap in `logger.debug`); the root cause is known and these were diagnostic-only.
2. Add a preflight check in `ingress.resolve_intent` that warns when `intent.state` exists but `intent.state.branch != intent.branch` — pre-empts future contamination questions.
3. Consider whether `strip_runtime_state` should run during the engine's MERGE *stage entry* (defensive) rather than only as a sequenced effect — so state stays clean even if the merge sequence aborts mid-way.

## What NOT to do

- Don't reopen settled smoke scenarios (1, 2, 3, 4, 5b, 6) unless test_plan flags them stale.
- Don't migrate to feature-slicing or full DDD — both are out-of-scope per `docs/architecture.md` §9 until trigger conditions fire (3+ feature areas with no shared code; 3+ bounded contexts).
- Don't autocreate labels every dispatch — once-per-repo is enough and avoids API rate cost.

Good luck.
