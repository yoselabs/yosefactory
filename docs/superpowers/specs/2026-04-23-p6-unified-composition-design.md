---
title: "P6 — Unified composition"
type: spec
status: Executed
owner: "@iorlas"
created: 2026-04-23
updated: 2026-04-23
rfc: "../../rfcs/0001-v1-scope.md"
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (V1.0 execution session 2026-04-23)"
---

# P6 — Unified composition

## Goal

Kill the `DISPATCHER_URL` env-branch in `cli/dispatch.py` and the
divergence between `cli/dispatch.py` and `cli/run_stage.py`. Introduce
`CompositionProfile` — a frozen dataclass naming which adapters,
subscribers, and credential profile this run uses — and two builder
functions (`build_adapters`, `build_subscribers`) that take a profile
and produce the wiring. Both CLI subcommands compose a `RunContext`
through the same code path; the subcommands differ only in how they
*resolve* the profile (`dispatch`: from env; `run-stage`: from CLI
flags + defaults).

After P6:

- "Mode 1" and "Mode 2" names disappear from engine code. Profiles are
  named `ci-dispatcher`, `ci-github-native`, `local-file` (internal
  tag only — there's no public enum).
- `cli/dispatch.py` drops from 331 LOC to ≤ 120 LOC.
- `adapters/factory.py`'s `NotImplementedError` arms for `github_issue`
  work + `github` review get filled in, so the same factory serves
  CI and local.
- N8's credential-profile slot exists (as `Literal["github_token",
  "dual_app"]`); the `"dual_app"` arm raises `NotImplementedError`
  until N8 wires real two-App execution.

V1.0 success criterion: a single `RunContext` construction path backed
by a declarative profile. The word "mode" survives only as a config
shorthand, not as branching logic.

Sixth V1.0 migration-phase spec. Appetite: **4–5 days.**

## Non-goals

- **No new top-level package.** `composition/` is a P7 relocation per
  vision §7.1 / §10. In P6, profile + builders live at
  `assembly/composition.py` alongside the existing `assembly/wire.py`.
- **No YAML profile config.** The profile resolves from `env +
  ProjectConfig`. YAML-declared profiles (vision §7.5 example dict)
  are post-V1.0.
- **No configurable middleware order.** P5 fixed
  `with_idempotency(with_telemetry(run_stage))`. No `profile.middleware`
  slot in V1.0; the first call site that needs to vary middleware will
  earn the field back.
- **No N8 execution.** `credential_profile` is a shape-only slot.
  `"dual_app"` raises `NotImplementedError`. N8 lights it up with its
  own operational work (reviewer App provisioning, installation-token
  rotation).
- **No `assembly/wire.py` rename to `observability/wire.py`.** P7.
- **No runner slot in the profile.** V1.0 always uses
  `SdkStageRunner(effort=config.effort)`. Second runner class = second
  slot.

## Plan

Each step = one commit. 8 steps. Each step must leave `make check`
green.

1. **Introduce `assembly/composition.py` with `CompositionProfile` +
   type-level tests only.**
   Dataclass + `Literal` unions. No resolver, no builders, no callers
   yet. L1 test: construct all three V1.0 profiles by hand, assert
   field access. **No behavior change.**

2. **Complete `adapters/factory.py`.**
   Fill the `NotImplementedError` arms for `github_issue` work (moves
   the `GitHubWorkAdapter.from_token` construction out of
   `cli/dispatch.py`) + `github` review (moves the
   `GitHubReviewAdapter` construction). Add a `workflow_input` work
   arm using `WorkflowInputReader`. Preserve the
   `GITHUB_TOKEN`/`GH_TOKEN` fallback. No callers use the new arms
   yet — existing code still hand-wires. L1 tests per arm.

3. **Add resolver + validator.**
   `resolve_composition_profile(env, config, *, mode)` +
   `validate_profile(profile)` in `assembly/composition.py`.
   L1 tests: each of the three V1.0 paths returns the expected
   profile; validator rejects illegal combinations
   (`workflow_input` work requires `dispatcher_event` subscriber;
   `dual_app` credential profile raises `NotImplementedError`).

4. **Add builders.**
   `build_adapters(profile, ...) -> (work, git, review, runner)` +
   `build_subscribers(profile, progress_state, ...) ->
   make_comment_subscriber | None` in `assembly/composition.py`.
   Builders are thin wrappers that call into `adapters/factory` per
   slot and attach subscribers to `progress_state` per
   `progress_subscribers` tuple. Runner is always
   `SdkStageRunner(effort=config.effort)`. L1 tests: each profile
   builds a `RunContext`-ready tuple of adapters + callable.

5. **Migrate `cli/dispatch.py`.**
   Collapse the 46-LOC if/else + the per-mode imports into
   `profile = resolve_composition_profile(os.environ, config,
   mode="dispatch")` + `build_adapters(...)` + `build_subscribers(...)`.
   Keep `_notify_stage_failure` as-is; rename
   `_derive_mode2_run_id` → `_derive_github_native_run_id`. Target
   dispatch.py ≤ 120 LOC.

6. **Migrate `cli/run_stage.py`.**
   Same pattern, `mode="run-stage"`. The existing `adapters/factory`
   imports here now go through `build_adapters` so both subcommands
   share one wiring path.

7. **Kill residuals.** Grep for `"Mode 1"` / `"Mode 2"` /
   `dispatcher_url` in engine code. Any stragglers in
   comments/docstrings/log messages that refer to the old modes become
   `profile=ci-dispatcher` / `profile=ci-github-native` phrasing, or
   get dropped. Update `CLAUDE.md` if it mentions Mode 1/Mode 2.

8. **Spec status → Executed.**

## File-level changes

| File | Change |
|---|---|
| `packages/engine/src/a2sdlc/assembly/composition.py` | **New** — profile dataclass, resolver, validator, builders. |
| `packages/engine/src/a2sdlc/adapters/factory.py` | Modified — fill arms for `github_issue` + `github` + `workflow_input`. |
| `packages/engine/src/a2sdlc/cli/dispatch.py` | Modified — if/else collapses. Target ≤ 120 LOC. |
| `packages/engine/src/a2sdlc/cli/run_stage.py` | Modified — same profile-driven path. |
| `tests/assembly/test_composition.py` | **New** — L1 profile + resolver + validator + builder tests. |
| `tests/integration/test_composition_roots.py` | **New** — L2 contract: each V1.0 profile produces a valid RunContext. |
| `tests/adapters/test_factory.py` | Modified — cover the newly-wired arms. |

## Target shapes

### `CompositionProfile`

```python
@dataclass(frozen=True)
class CompositionProfile:
    work: Literal["github_issue", "workflow_input", "local_file"]
    review: Literal["github", "local_noop"]
    git: Literal["local", "local_branch"]
    progress_subscribers: tuple[str, ...]
    # ^ "gh_comment" | "dispatcher_event" | "console"
    credential_profile: Literal["github_token", "dual_app"]
```

### Resolver

```python
def resolve_composition_profile(
    env: Mapping[str, str],
    config: ProjectConfig,
    *,
    mode: Literal["dispatch", "run-stage"],
) -> CompositionProfile:
    if mode == "run-stage":
        return CompositionProfile(
            work="local_file",
            review="local_noop",
            git="local_branch",
            progress_subscribers=("gh_comment",),
            credential_profile="github_token",
        )
    # mode == "dispatch"
    if env.get("DISPATCHER_URL"):
        return CompositionProfile(
            work="workflow_input",
            review="github",
            git="local",
            progress_subscribers=("dispatcher_event", "console"),
            credential_profile="github_token",
        )
    return CompositionProfile(
        work="github_issue",
        review="github",
        git="local",
        progress_subscribers=("gh_comment",),
        credential_profile="github_token",
    )
```

### Validator

```python
def validate_profile(profile: CompositionProfile) -> None:
    if profile.work == "workflow_input" and "dispatcher_event" not in profile.progress_subscribers:
        raise ValueError("workflow_input work adapter requires dispatcher_event subscriber")
    if profile.credential_profile == "dual_app":
        raise NotImplementedError("dual_app credential profile is N8 — not wired in P6")
```

### CLI after P6 (dispatch subcommand)

```python
def dispatch_command(...) -> None:
    root = find_project_root()
    config = load_config_file(root)
    setup_logging("dispatch", "dispatch", root)

    telemetry = telemetry_from_env(experiment_name=root.name)
    progress_state = build_progress_state(
        root, config.adapters.progress,
        with_mlflow_trace=telemetry.traces_enabled,
    )

    profile = resolve_composition_profile(os.environ, config, mode="dispatch")
    validate_profile(profile)

    work, git, review, runner = build_adapters(
        profile,
        project_root=root, session_id=..., stage=...,
        config=config, env=os.environ,
    )
    make_comment_subscriber = build_subscribers(
        profile, progress_state, env=os.environ,
    )

    ctx = RunContext(
        work=work, git=git, review=review, runner=runner,
        progress_state=progress_state, config=config, project_root=root,
        logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
        make_comment_subscriber=make_comment_subscriber,
        telemetry=telemetry,
        run_id=_resolve_run_id(profile, os.environ),
    )
    # ... existing asyncio.run(dispatch(ctx)) + failure-notify path unchanged
```

## Test strategy

- **L1 per-component.** Profile construction (step 1), factory arms
  (step 2), resolver mappings (step 3), builder assembly (step 4).
  Each step ships its own L1 tests.
- **L2 contract.** One test per V1.0 profile: resolver → validator →
  builders produce an `asyncio.run(dispatch(ctx))`-ready `RunContext`
  against `tests/fakes`. `ci-dispatcher` test uses an in-memory
  `WorkflowInputReader`; `ci-github-native` uses cassette-backed
  `GitHubWorkAdapter`; `local-file` uses the file-backed fakes.
- **L3 integration.** Existing cassette tier (13 tests) stays green —
  factory arms are moving code, not changing behavior. Re-record only
  if an adapter constructor signature changes (it shouldn't).
- **L6 smoke.** Run the CLI local smoke test after step 6. Load-bearing
  end-to-end check that both subcommands still work against real fakes.

## Security considerations

- **Credential-scope invariants preserved.** Today's `GITHUB_TOKEN` /
  `GH_TOKEN` fallback in `cli/dispatch.py` Mode 2 is preserved by the
  factory's `github` arm; regression-tested in step 2. Token never
  leaves the adapter layer.
- **`credential_profile="dual_app"` fails loudly.** Raising
  `NotImplementedError` (not silently degrading to `github_token`)
  means an accidental config that names `dual_app` in a future YAML
  surface will break the build, not silently self-approve.
- **No new external surface.** All changes are internal reshapes +
  adapter factory completion. The constructor arguments and HTTP/API
  shapes are unchanged.

## Rollout

Ships on main one step at a time. Highest-risk step is **step 5**
(`cli/dispatch.py` migration) — a CI env variable consumed by the old
if-branch but not by the new builder would silently break a GHA run.
Mitigation: step 5 reads the same env vars the old code reads; a unit
test captures the full env-var list per profile and asserts each is
consumed during build.

Steps 1–4 are pure additions: each ships with the existing dispatch
path still hand-wired. Steps 5–6 are the load-bearing CLI migrations.
Step 7 is documentation/residual cleanup. Step 8 is status flip.

Not feature-flagged. Composition changes don't benefit from runtime
toggles.

## Backout

- Step 1–4 revert: pure additions, trivially revertible.
- Step 5 revert (load-bearing): single-commit revert restores the
  hand-wired `cli/dispatch.py`. The new profile + builders survive
  as dead-but-tested code until re-applied.
- Step 6 revert: independent of step 5; `cli/run_stage.py` returns
  to hand-wired factory calls.
- Step 7 revert: rename rollback only; no behavior change.

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Architecture vision §7.5 (mode-agnostic composition root — the P6 target)
- Architecture vision §8 ("Composition roots: 2 divergent → 1")
- RFC §N8 (credential profile slot — P6 ships the shape, N8 ships execution)
- P5 spec (prerequisite): `2026-04-23-p5-middleware-design.md`
