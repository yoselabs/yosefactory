Motivation: see [proposal.md](proposal.md) — Why. Requirements: see
`specs/containerized-loop/unattended-isolation-posture/spec.md` and
`specs/claude-executor/isolation-invocation/spec.md`.

## Context

`run-the-factory-in-a-container` built `Dockerfile`, `docker-compose.yml`, and
`docker-entrypoint.sh`. Nobody has run the loop's actual work through them. Last night's one real
attempt on the host (not the container) hit two failures:

1. A turn's raw transcript (`ledger/runs/*.stream.jsonl`) — the executor's raw stdout — carried
   the operator's home directory 53 times and got committed to this public repo. A guard now
   exists (`tools/hooks/forbid-host-paths.py`, `.gitignore` excludes the transcript path). That is
   the seatbelt. It does not need to fire inside a container, because the transcript can only
   contain what the process running inside the container could see, and a container with only its
   workspace mounted cannot see `/Users/...` at all — the fix here is not code, it is *actually  hostpath-allow
   running inside the container*, which this change's receipt is the first to do.
2. `runtime/loop.py::main()` hardcodes `IsolationPolicy(isolated=True)` for every invocation,
   interactive or scheduled. `isolated` means safe-mode plus `--permission-mode manual`
   (`executor/claude.py::build_argv`) — every tool call needs human approval. An unattended
   invocation has no human to approve anything, so the run does nothing and ends
   `needs_approval`. `scheduled_main` — the function `yosefactory-loop-scheduled` (the container's
   own `CMD`) calls — inherits this through `main(unattended=True)`.

Denis's ruling, applied rather than re-derived: carte blanche for the agent inside its workspace,
no permission prompts; the only controls are `--max-iterations` and `--spend-ceiling-usd`
(`scheduled_main` already makes the latter mandatory); everything isolated from the operator's Mac;
the agent must not reach other projects or damage the factory itself.

## Goals / Non-Goals

**Goals:**
- `scheduled_main` no longer defaults to a posture that denies tool calls.
- State, per boundary, whether it is enforced by container mount topology or by policy (a flag).
- Reuse the existing `Dockerfile`/`docker-compose.yml`/`docker-entrypoint.sh` — adjust only if the
  live receipt shows an actual defect.
- A real turn, run inside the built container against yosefactory's own backlog, with its ledger
  record, `.wake.json`, and spend row read back from the host, and its transcript grepped for
  `/Users/` from outside the container.  hostpath-allow
- A demonstrated (not described) attempt to reach something outside the workspace from inside the
  container.

**Non-Goals:** see proposal.md — Non-goals. In particular: no multi-repo pointing, no production
deployment posture (registry, restart policy, UID/GID), no role/workflow object.

## Decisions

### D1 — Fix the entrypoint default by branching on `unattended`, not by adding a new flag

**Chosen:** `main()` already threads `unattended: bool` through to gate `--spend-ceiling-usd`'s
requiredness (D022's reasoning: a human is or is not present). The isolation posture branches on
the same signal:

```python
policy = (
    IsolationPolicy(
        isolated=False,
        workspace_scoped=True,
        opt_out_reason=(
            "unattended (scheduler/container) invocation: the container's mount topology, not "
            "this policy, is what bounds what the run can reach outside its workspace; "
            "workspace_scoped + a non-denying permission mode is required for real work with no "
            "human present to approve a prompt"
        ),
    )
    if unattended
    else IsolationPolicy(isolated=True)
)
```

`main()` called directly (`unattended=False`, the only way a person invokes it) is byte-for-byte
unchanged. `scheduled_main()` — and therefore the container's `CMD` — gets `workspace_scoped`.

**Over:** (a) a new CLI flag (`--isolation-posture`) — rejected, it reopens exactly the "omission
produces an opt-out" hole `IsolationPolicy.__post_init__` and `resolve()` already exist to close;
a flag with a default is a default, and this default already has an unattended-vs-interactive
signal available for free; (b) leaving `isolated=True` and instead trying to make safe-mode's
`manual` permission mode non-denying — rejected, `agent-isolation`'s own spec already requires the
isolated posture stay a floor that admits no additions, and `manual` is what makes an isolated run
safe for a host session where a person genuinely might be asked; changing its behavior would
change what `isolated` means for every existing caller, not just the container's.

### D2 — `workspace_scoped` gets a non-denying permission mode in `build_argv`, unconditionally

**Chosen:** `build_argv`'s non-isolated branch adds `--permission-mode bypassPermissions` whenever
`policy.workspace_scoped` is true — not gated on a separate "unattended" argument to `build_argv`
itself. `workspace_scoped` currently has exactly one real caller once this change ships
(`scheduled_main`, via D1) plus its own test fixtures; there is no existing interactive caller of
`workspace_scoped` that this could regress, and adding an "unattended" parameter to `build_argv`
would duplicate a distinction `IsolationPolicy` already exists to carry.

**Over:** `acceptEdits` — narrower (accepts file edits, still gates other tool categories);
rejected because Denis's ruling is carte blanche inside the workspace, not "edits only," and a
narrower mode would silently reintroduce the same `needs_approval` failure for whichever tool
category it does not cover. `claude --help` states `--dangerously-skip-permissions` /
`bypassPermissions` are "recommended only for sandboxes with no internet access" — this run has
internet access (the executor itself needs it to reach the API), which is a real caveat: the
mitigation is not "no internet," it is "nothing reachable through that internet access is worth
protecting," which is what D3/D4 below establish for the container's mount topology and D2 of the
prior change already established for auth (a subscription token, not the operator's own
long-lived credentials).

### D3 — What is topology, what is policy: the actual boundary table

Per `unattended-isolation-posture`'s own requirement that this be stated, not implied:

| Boundary | Mechanism | Kind |
|---|---|---|
| Cannot read the operator's other repositories/projects | Nothing but the yosefactory repo (and, if separated, its workspace path) is bind-mounted into the container. The paths do not exist inside it. | **Topology** |
| Cannot read the operator's host credentials (keychain, SSH keys, `gh` login, `~/.claude` host state) | Not mounted; the container's only credential is `CLAUDE_CODE_OAUTH_TOKEN` in the environment (prior change, D2). | **Topology** |
| Cannot see the host's user-level `CLAUDE.md`, skills, plugins, or `settings.json`-declared MCP servers | `--setting-sources project,local` (the `workspace_scoped` mechanism) — a flag, evaluated by the binary. A misconfigured invocation could omit it. | **Policy** |
| Tool calls inside the workspace are not gated by human approval | `--permission-mode bypassPermissions` — a flag. | **Policy** |
| Cannot push to `origin` / act with the operator's own git identity | No git credential helper, no SSH key, no `gh` auth token mounted or present in the image. | **Topology** |

The topology rows hold even if every policy row above them is misconfigured, because the
unreachable thing is not present in the container's filesystem regardless of what flags were
passed. The policy rows hold only as long as the flag is correct on that invocation — this is
weaker, named as such, and is why D1 resolves it through `IsolationPolicy` (a single, tested,
`__post_init__`-validated construction point) rather than through an ad-hoc flag at the call site.

### D4 — The receipt's workspace is yosefactory itself; no separate `.dev-workspace`

The prior change's `docker-compose.yml` bind-mounts `./:/app` (source, dev) and a *separate*
`./.dev-workspace:/data/workspace` (the loop's queue+workspace) specifically to avoid the mount
race (D1 of that change) for the *general* case of pointing the loop at an arbitrary repository.
This change's proposal explicitly excludes pointing the loop at any repository other than
yosefactory itself (Non-goals) — the receipt's backlog items are about yosefactory's own code.
Rather than fabricate a throwaway `.dev-workspace` repo whose only content would be "yosefactory
again," the receipt run points `Places.local` at `/app` directly: one mount, the same path serving
as both source and workspace, `_refuse_if_dirty` still enforced. This is a narrower configuration
than the compose file's own default (still available unmodified for the general dev case) — the
receipt uses `docker compose run` with an overridden `command` and volumes rather than editing the
shipped default, so the default posture the prior change built and specified is not disturbed by
this one. **Stated plainly:** in this specific configuration, the source-mount/workspace-mount
separation D1 (prior change) exists to defend against does not apply, because there is nothing to
separate the workspace from — the workspace *is* the source, on purpose, for this receipt only.

## Risks / Trade-offs

- **`bypassPermissions` is a broad grant.** [Risk] the agent can run any tool without a check.
  → [Mitigation] this is the ruling, not a gap: the only remaining controls are
  `--max-iterations` and `--spend-ceiling-usd`, both already mandatory on `scheduled_main`, and the
  container's topology (D3) bounds the blast radius to the workspace regardless of what the agent
  decides to do inside it.
- **D4's single-mount receipt configuration is not what a future multi-repo posture would use.**
  [Risk] someone reads the receipt's compose invocation as the shipped default. → [Mitigation]
  stated explicitly in D4 and in the receipt's own commit message; the shipped `docker-compose.yml`
  default is untouched by this change unless the live run surfaces a real defect in it.
- **A container-run agent proposing `done` without committing its own work** (a real failure from
  the second host attempt last night) is a known, separate issue. → Not fixed here (Non-goals); if
  hit again, reported as a finding, not patched into the skill as part of this change.

## Migration Plan

No data migration. Code change is additive/branching (D1) and a single new flag in one branch
(D2); existing `isolated` callers and tests are unaffected. Rollback is reverting the two commits
that change `main()`'s branch and `build_argv`'s `workspace_scoped` branch.
