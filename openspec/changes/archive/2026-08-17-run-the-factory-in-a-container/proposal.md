# run-the-factory-in-a-container

Supersedes `add-scheduled-loop`, retired same session: Denis answered at a higher level than that
dispatch asked. *"the whole factory should run ideally inside a docker... potentially in
development time we will mount the folder... to keep things running in docker via docker compose
during development without the refresh."* **The container is the deliverable; a scheduler is one
thing that runs inside it, not the point of it.**

## Why

`add-scheduled-loop` built a `launchd` install path and it never got past its own receipt: the
first unattended fire ran `take_turn` against this actual checkout while it held uncommitted
change work, and `prek`'s tree-wide stash-on-hook-run collided with `take_turn`'s own commit —
`TurnError: commit refused: Restored working tree changes from .../prek/patches/....patch`. No
data was lost (the commit was refused, not corrupted) and no money was spent (the failure was in
the queue-commit step, before any executor call). But it is the most valuable thing that detour
produced, and Denis is explicit it must not be lost: **a development bind mount reproduces this
exact condition by construction** — the mount that makes editing pleasant is the same mount that
lets the loop race a human editing the same files. Design section "The mount race" below is the
answer, not a footnote.

`launchd` also does not fit what was actually asked: a per-user agent lives on Denis's own host,
permanently, outside any container boundary — the opposite of "runs inside a docker." Retiring it
is not a smaller version of the same change; it is Article VII (exploration overturning a
dispatch), one level up, for the dispatch that came before this one.

## What Changes

- **`Dockerfile`** — builds a Linux image carrying `uv`, the pinned `claude` binary
  (`executor/claude.py::PINNED_VERSION`, matched exactly — a different version is a different
  capability map, per that module's own docstring), and the package installed editable.
- **`docker-compose.yml`** (dev) — bind-mounts the repository source so a code edit takes effect
  without a rebuild, keeps the virtualenv **outside** the mounted path so the mount cannot shadow
  it, and mounts the loop's queue/workspace from a **separate** directory than the source mount —
  the mechanism that avoids the mount race (see design.md).
- **`scheduled_main()` / `[project.scripts]` carried forward unchanged** from `add-scheduled-loop`:
  the container's `command:` invokes `yosefactory-loop-scheduled`, whose mandatory
  `--spend-ceiling-usd` is exactly as valuable inside a container as it would have been under
  `launchd` — nothing about the D022 argument was specific to the scheduler.
- **`.env.example`** — names the two possible auth env vars (`ANTHROPIC_API_KEY`,
  `CLAUDE_CODE_OAUTH_TOKEN`) with empty values and provenance comments; `.env` itself is already
  gitignored (pre-existing entry). No credential of any kind is committed.
- **A startup dirty-tree guard in `runtime/loop.py`** — `run_loop` refuses to start (clear
  `LoopError`, before any `take_turn` call) if `places.workspace` has uncommitted changes at the
  moment it is invoked, rather than discovering the same condition three layers down inside
  `prek`'s stash mechanism with a confusing message. Defense in depth under the mount race: the
  primary mitigation is "don't point the loop at the source mount", this is the fallback for when
  someone does anyway.
- **`ops/launchd/` deleted entirely.** Nothing installs into Denis's host — hard constraint, not a
  preference, per this dispatch.

## Capabilities

### New Capabilities
- `containerized-loop/dev-and-production`: the factory (loop + entrypoints) builds and runs as a
  Docker image; a `docker compose` dev configuration bind-mounts source for live edits without a
  rebuild while keeping the loop's own queue/workspace on a separate mount from the source tree;
  the loop's ledger and spend records are readable from the host after a container-run turn; no
  credential is baked into the image or committed to the repository.

### Modified Capabilities
None promoted from `add-scheduled-loop` (nothing of it was ever archived — the whole change is
retired, its directory deleted, per Article XIV's own scope: nothing here is a MODIFIED block
against an existing promoted spec).

## Impact

- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example` — new.
- `src/yosefactory/runtime/loop.py` — `main()`/`scheduled_main()` carried forward as built in
  `add-scheduled-loop` (this change re-applies them, since that change's directory is deleted
  without ever having been archived — nothing was promoted to `openspec/specs/` for it to
  conflict with); new `_refuse_if_dirty` startup guard in `run_loop`.
- `tests/runtime/test_loop.py` — the three `scheduled_main` tests carried forward; new tests for
  the dirty-tree guard.
- `pyproject.toml` — `[project.scripts]` carried forward.
- `ops/launchd/` — deleted (was already deleted when `add-scheduled-loop` was retired, ahead of
  this proposal; recorded here so the change's own diff accounts for it).
- `.gitignore` — no change needed; `.env` is already listed.

## Non-goals

- **A CI/production deployment target for the image** (a registry push, a orchestrator manifest).
  Out of scope — this change proves the loop runs in a container and is observable from outside
  it; where the built image is deployed in production is Denis's call, not designed here.
- **Matching container UID/GID to the host user via a build arg.** Noted as a real platform
  difference in design.md (Platform) but not built: this is a personal single-developer image, and
  the mount-ownership friction it would prevent is cosmetic (`chown` after the fact) rather than a
  correctness or security problem, unlike the auth and mount-race issues, which are.
- **A credentialed live receipt without Denis's explicit input.** The mechanism (`ANTHROPIC_API_KEY`
  or `CLAUDE_CODE_OAUTH_TOKEN` via a local, gitignored `.env`) is built and documented; supplying
  the actual secret is his action, not this change's.

## The receipt question (Article XVI)

**What would distinguish built from works:** `docker compose up` succeeding, or `docker compose
exec factory claude --version` returning the pinned version, are both instrument-only (S194) —
they prove the container starts and the binary is reachable, not that the loop ran anything. The
receipt is: run `yosefactory-loop-scheduled` (or `docker compose run`) **inside** the container
against a mounted queue directory, then — from the **host**, outside the container, in a fresh
shell — read `ledger/runs/*.json` and its `.wake.json` sidecar off the mounted path and confirm a
record exists with a timestamp inside the run window. A `nothing-ready` turn proves this at $0; a
real item consumed proves the executor path too, and needs the credential Denis has not yet
supplied — held, not fabricated, if it stays blocked.
