## Why

`run-the-factory-in-a-container` built the image and compose file but the loop's real work has
never run inside them. Two real failures from the first live host run last night show why that
gap matters: a turn's raw transcript, full of `/Users/iorlas/...` host paths, got committed to  hostpath-allow
this public repo (caught before push; a gitignore + `tools/hooks/forbid-host-paths.py` now exist
as a seatbelt) — and the shipped entrypoint (`runtime/loop.py::main`) hardcodes
`IsolationPolicy(isolated=True)` unconditionally, which is safe-mode plus
`--permission-mode manual`: every tool call needs human approval, and an unattended run has no
human, so it ends `needs_approval` having done nothing. No promotion id — this is a direct
dispatch, not a K project 160 write-back; the design record it bears on is P160's
`orchestration.md`/`build-loop.md` observation that host-run receipts are weaker than they look
because the host supplies things production will not have.

## What Changes

- `runtime/loop.py::main()` no longer applies the interactive-host isolation default to unattended
  invocation. `scheduled_main` (the container's entrypoint) now defaults to a `workspace_scoped`
  posture instead of `isolated`; `main()` called directly (a person, on a laptop, no container)
  is unchanged.
- `executor/claude.py::build_argv` emits a permission mode that does not deny tool calls
  (`--permission-mode bypassPermissions`) for the `workspace_scoped` posture — today it emits none,
  which under `-p` non-interactive invocation behaves like the same denial the `isolated` posture
  produces. `isolated` (safe-mode, `manual`) is unchanged.
- The container's filesystem topology (only the workspace mounted; no host filesystem, no other
  repositories, no host credential store) becomes the actual mechanism for "cannot reach anything
  else" — stated explicitly as topology, not policy, alongside the one piece that remains policy
  (no prompts inside the workspace).
- A real turn runs inside the built container, against yosefactory's own backlog, as the receipt:
  its ledger record, `.wake.json`, and spend row are read back from the host, and its transcript is
  grepped for `/Users/` from outside the container (host paths do not exist inside the container,  hostpath-allow
  so the transcript-publication risk resolves at the source rather than only being caught by the
  guard).

## Capabilities

### New Capabilities
- `containerized-loop/unattended-isolation-posture`: what posture the container's entrypoint uses
  by default, and which parts of "the agent cannot reach outside its workspace" are topology versus
  policy.

### Modified Capabilities
- `claude-executor/isolation-invocation`: the `workspace_scoped` posture's translation into
  invocation arguments now includes a permission mode that does not require human approval.

## Impact

- `src/yosefactory/runtime/loop.py` — `main()`'s policy selection.
- `src/yosefactory/executor/claude.py` — `build_argv`'s non-isolated branch.
- `Dockerfile` / `docker-compose.yml` / `docker-entrypoint.sh` — reused as built by
  `run-the-factory-in-a-container`; adjusted only if the live receipt shows a real defect, not
  speculatively.
- `ledger/` — a real run's records, committed as the receipt.
- Tests: `tests/executor/test_integration.py`, `tests/runtime/` (entrypoint default).

## Non-goals

- The multi-session/role idea — roles are states, sequencing stays the fold ([[S173]]); no
  workflow object.
- Production deployment: registry, restart policy, UID/GID matching.
- Pointing the loop at any repository other than yosefactory itself.
- Fixing an agent proposing `done` without committing its own work, if hit again — that is a
  separate, already-known defect; report it, do not patch the skill here unless it falls out for
  free.
