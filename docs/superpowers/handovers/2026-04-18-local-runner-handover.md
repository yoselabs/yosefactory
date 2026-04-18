# Local Runner Handover — 2026-04-18

## Status

Branch `feat/local-runner` is **feature-complete, all-green for the fake-runner test path, AND validated end-to-end against the real Claude Agent SDK** (smoke run on 2026-04-18, session `smoke2`).

- **Commits:** 21 (`main..HEAD`)
- **Tests:** 496 passing
- **`make check`:** green
- **Smoke validation:** SPEC + IMPLEMENT both green from a clean repo. Skills load (brainstorming, writing-plans, requesting-code-review observed in tool log). TDD flow runs end-to-end. Engine quality gate fires; MLflow records parent + child runs.

## What's Done

See `docs/superpowers/specs/2026-04-18-a2sdlc-local-runner-design.md` (revision 4) for the full design. Shipped:

- Config migration to `.a2sdlc/config.yaml` with strict keys + `adapters`/`quality` blocks + `effort` field
- Cleanup of legacy `ProjectConfig` fields (`adapter`, `trigger_mention`, `test_command`) and dead `cli.py` branch
- `ProgressAdapter` protocol + `GhActionsProgressAdapter` + `ConsoleProgressAdapter` (rich.Live)
- Three local adapters: `LocalBranchGitAdapter`, `LocalNoopReviewAdapter`, `LocalFileWorkAdapter`
- Adapter factory (`adapters/factory.py`)
- `ProgressAdapter` wired into `dispatch.py` and `runner.py` (with print fallback)
- `a2sdlc run-stage` CLI via new `cli_local.py`
- MLflow telemetry: parent run per session, nested child runs per stage, metrics + tags
- Post-implement quality gate (affects CLI exit code, does NOT block subsequent stages)
- End-to-end integration tests for spec → implement with FakeStageRunner
- `docs/local-runner-usage.md` + README section
- Spec self-review pattern added to `prompts/stages/spec.md` (two review loops, matching IMPLEMENT)
- `effort` config threaded into `ClaudeAgentOptions.effort`
- `setting_sources=["project", "local"]` to exclude user-level CLAUDE.md / auto-memory

Engine invariant holds: `pipeline/dispatch.py`, `pipeline/runner.py`, `pipeline/context.py` got minimal additive changes (progress field, stats field, print→adapter swap, setting_sources, effort). No stage/domain/lifecycle/assembly code modified.

## Resolved

### 1. Smoke test ✅ validated

Two clean runs against the real SDK:

| Session | Stage | Cost | Notes |
|---|---|---:|---|
| smoke1 | spec | $0.16 | killed mid-run during initial investigation; later re-ran as no-op |
| smoke1 | implement | $0.48 | TDD flow, quality gate green |
| smoke2 | spec | (in MLflow) | clean run from empty repo, brainstorming + writing-plans skills observed |
| smoke2 | implement | $0.32 | full TDD + post-impl `requesting-code-review` skill |

Workspace at `/Users/iorlas/Workspaces/a2sdlc-smoke/` (still on branch `a2sdlc/smoke2`).

### 2. Open question ✅ answered: skill loading works

`setting_sources=["project", "local"]` does **NOT** disable user-level Superpowers plugins. The smoke runs invoked `Skill(brainstorming)`, `Skill(writing-plans)`, and `Skill(requesting-code-review)` successfully without any plugin-loading workaround. **No `plugins=[...]` fix needed.**

### 3. Scope bleed (partially addressed)

Before the `setting_sources` fix, the agent was:
- Reading `/Users/iorlas/Documents/Knowledge/global-claude.md` (auto-memory)
- Reading `/Users/iorlas/Documents/Knowledge/Agents/Claude/MEMORY.md`
- Running `ls /Users/iorlas/dev/` (wandering outside the target repo)

The `setting_sources` fix kills the memory loading. But the Bash tool still accepts absolute paths anywhere. **Future:** tighten `spec.md` prompt with "operate only inside the project_root at {cwd}" AND/OR add permission rules to `ClaudeAgentOptions.allowed_tools` that fence Bash to project-relative paths.

## Known Follow-ups (punch list, non-blocking)

- Unify Jira/GitHub adapters through the factory (currently raise `NotImplementedError`)
- Taskmaster pre-spec decomposition
- `a2sdlc sessions prune` subcommand
- Per-stage LLM-as-judge scoring
- Worktree adapter for parallel A/B runs
- `review_cycles` threaded into `get_session_id` for true cold re-review
- Shared MLflow server (Dokploy-hosted)
- `gates.merge=AUTO` in local config (currently synthetic approval satisfies HUMAN gate)
- Runner `print` fallback still hardcodes `::group::` — unreachable in production but cosmetic
- Agent-level file-system fence (absolute paths)

## Invocation Notes

- `a2sdlc` is globally available via `uv tool`. If the engine source changes, changes flow automatically (editable install).
- Config: `.a2sdlc/config.yaml` — strict keys, fail-fast if missing.
- MLflow store: `~/.a2sdlc/mlflow/` — use `mlflow ui --backend-store-uri ~/.a2sdlc/mlflow` to browse.
- Auth: the SDK piggybacks on Claude Code's subscription login (no `ANTHROPIC_API_KEY` required).
- Subagent model choice: left to the primary agent per dispatch (no `subagent_model` config field).

## Merge Readiness

**Both blockers cleared.** Branch is ready to merge to `main`.

Optional follow-up before merge: the `ConsoleProgressAdapter` status bar shows `tokens: 0/0 | cost: $0.00 | turns: 0` throughout local runs because `update_metrics()` is defined but never called by the runner. Tracked as a separate spec on this branch (see `docs/superpowers/specs/2026-04-18-progress-subscribers-design.md` once committed) — addresses the underlying "two channels for the same data" smell, not just the symptom.
