# Local Runner Handover — 2026-04-18

## Status

Branch `feat/local-runner` is **feature-complete and all-green for the fake-runner test path**, but has NOT been validated end-to-end against the real Claude Agent SDK. Smoke test was started and killed after surfacing a scope-bleed issue; the fix is committed but unvalidated.

- **Commits:** 19 (`main..HEAD`)
- **Tests:** 496 passing (up from 391 pre-branch)
- **`make check`:** green
- **Last commit:** `c2b0398 feat(runner): exclude user setting sources from SDK sessions`

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

## What's Mid-Flight (PICK UP HERE)

### 1. Smoke test not validated

A fresh workspace exists at `/Users/iorlas/Workspaces/a2sdlc-smoke/` with:
- `.a2sdlc/config.yaml` using local adapters + `model: claude-sonnet-4-6` + `progress: console`
- `ticket.md` asking for a `reverse_words` Python function with 4 test cases
- `Makefile` with `check`/`test`/`lint` targets

a2sdlc is installed globally via `uv tool install --editable /Users/iorlas/Workspaces/a2sdlc-engine`.

**Run it:**
```bash
cd /Users/iorlas/Workspaces/a2sdlc-smoke
a2sdlc run-stage spec --ticket ticket.md --session smoke1 .
```

### 2. Open question — does `setting_sources=["project", "local"]` block Superpowers skill loading?

The SDK field `setting_sources` controls which settings.json files merge in. Excluding `user` likely also disables user-level plugins (like Superpowers `brainstorming`/`writing-plans`/`code-reviewer`). **Smoke test will tell us immediately** — if the agent's `Skill(brainstorming)` call fails, we know.

**Fix if broken:** pass `plugins=[SdkPluginConfig(type="local", path="/Users/iorlas/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7")]` in `runner.py:options_kwargs`. Five-line addition.

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

**Blockers before merging to main:**
1. One clean smoke run (SPEC → IMPLEMENT → quality gate green) against the real SDK.
2. Confirm skill loading still works (or apply the explicit plugin-load fix).

**Not blockers:** the punch-list items above.
