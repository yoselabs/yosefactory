# ADR-0017 — The dev compose source mount is read-only, with a startup write-guard

**Status:** Accepted
**Date:** 2026-08-24
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** the dev loop needs a container process to write into the source tree for a
legitimate reason (a codegen step, a formatter run meant to modify tracked files from inside the
container rather than the host) — at that point re-examine whether the mount stays `:ro` with an
explicit, narrower exception, or the boundary moves elsewhere.

## Context

[[S245]] (K project 160): `docker-compose.yml` mounted the machine's own source at `/app`
read-write alongside the loop's queue/workspace at `/data/workspace`. An unattended planning turn
read `/app` — a far more interesting repository than the near-empty workspace it was given — and
invented two backlog items about the factory itself. A following turn spent $6.67 running a full
OpenSpec cycle **inside `/app`**: branch `sweep-blocked-and-snoozed-deadlines`, three commits, 935
insertions across 11 files including `runtime/turn.py` and `protocol/backlog.py`, and left the
repository checked out on that branch. The next worker dispatched into the tree started from it,
unknowingly, until stopped.

D025 and the CI credential fencing hold for the *credential*, demonstrated with a hostile fixture.
They did not hold for the *source*: nothing in the compose topology stopped a turn's writes at the
workspace boundary. The mount existed for developer convenience (live-editable source, no rebuild
per edit) — convenience never required write access *from inside the container*, since the
developer's own editor already writes the host copy directly.

## Decision

`docker-compose.yml`'s source mount becomes `./:/app:ro`. Two tools were measured to need a write
inside `/app` to run at all against the built image: `ruff` (a cache temp file,
`.ruff_cache/.../\.tmp...`, fails hard with "Read-only file system") and `pytest` (`.pytest_cache`,
degrades to a warning rather than failing, but still attempted a write). Both are pointed outside
the mount via `Dockerfile` env vars — `RUFF_CACHE_DIR=/tmp/ruff-cache`,
`PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"` — set in the image rather than per-compose so
`make check` behaves the same under a bare `docker run` as under `docker compose`. `ty` and plain
`python -c "import yosefactory"` needed no change; measured directly against the built image with
the source bind-mounted `:ro`.

`docker-entrypoint.sh` additionally refuses to start `yosefactory-loop` or
`yosefactory-loop-scheduled` if the source root (`$YF_SOURCE_ROOT`, default `/app`) is writable —
a live check on the boundary this decision declares. `orchestration.md` names the failure mode
directly: *"a declared boundary with no live check is the S195 pattern."* A `:ro` flag in a YAML
file is exactly that kind of declaration; the entrypoint check converts a future compose
regression (someone drops `:ro` while debugging and forgets to restore it) into a loud startup
refusal instead of a silent reopening of S245.

**Two rejected alternatives**, both considered against S245's actual mechanism:

- **Drop the source mount, run the built image as-is.** `docker-compose.yml`'s own header already
  names this the production posture. Rejected for the dev loop specifically because it reintroduces
  a rebuild-per-edit cost the compose file exists to avoid; not wrong, just the wrong layer —
  deferred to whichever future change builds the production topology.
- **Keep the mount writable, deny by uid.** ADR-0007 fixes the container's user to uid 1000 so
  `bypassPermissions` is accepted by the `claude` binary — an *identity* constraint. It says
  nothing about the bind-mounted directory's ownership, which is the host's, not the container
  user's; there is no uid-based mechanism between "the mount is writable" and "it is not" that
  does not ultimately route through the mount flag itself. Rejected as solving the wrong layer of
  the problem, not as incorrect on its own terms.

## Consequences

- The dev loop stays live-editable exactly as before (`docker-compose.yml`'s own documented
  behavior: an edit under `src/` takes effect on the next command, no rebuild) — nothing about the
  edit workflow changes, because the developer's own editor never went through the mount to begin
  with.
- `make check` (`lint ty test citations`) passes inside a container built from the updated image
  with the source mounted `:ro` — measured directly, all four targets, `citations` skipping
  cleanly (no K checkout inside the container, expected).
- **Not proven by any automated check:** that the real Docker bind mount actually enforces
  read-only from inside a real running container, or that `make check` passes under the real
  `docker compose` invocation rather than the manually-driven `docker run` used to measure this.
  Both were verified by hand this session; neither is a standing check, because nothing in
  `make check` builds an image or runs a container. See
  `openspec/changes/stop-source-mount-being-writable/design.md`'s Verification section for the
  exact commands a human runs to re-check this.
- The entrypoint's write-guard is scoped to the two turn-running commands, matching the existing
  token check's scope — diagnostic invocations (`claude --version`, a shell) are unaffected.

## References

- `docker-compose.yml` — source mount `:ro`.
- `Dockerfile` — `RUFF_CACHE_DIR`, `PYTEST_ADDOPTS`.
- `docker-entrypoint.sh` — write-guard check, `$YF_SOURCE_ROOT`.
- `tests/scripts/test_entrypoint_write_guard.py` — drives the real script.
- `openspec/changes/stop-source-mount-being-writable/` (design.md, proposal.md).
- K signal S245, project 160, cluster C6.
