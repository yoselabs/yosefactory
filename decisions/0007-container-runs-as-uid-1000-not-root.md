# ADR-0007 — The container image runs as a fixed non-root user (uid 1000)

**Status:** Accepted
**Date:** 2026-08-20
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** the container's mount topology changes to require matching the host's mount
owner uid/gid (the UID/GID-matching concern `run-the-loop-inside-the-container`'s own Non-goals
deferred to production) — at that point uid 1000 fixed-and-unmatched needs re-examination against
whatever that production topology requires.

## Context

`run-the-loop-inside-the-container` (archived 2026-08-20) wired `build_argv`'s `workspace_scoped`
posture to emit `--permission-mode bypassPermissions`, the flag that lets an unattended turn run
tool calls without a human approving each one. The first real in-container turn under this flag
failed twice, structurally, at $0 each with no terminal event: the `claude` binary refuses
`bypassPermissions` outright when the process runs as root — measured directly, the binary's own
error is *"cannot be used with root/sudo privileges for security reasons"* — and the image's
`Dockerfile` up to that point ran everything as the default root user.

## Decision

`Dockerfile` adds `useradd --create-home --uid 1000 --shell /bin/bash factory` and switches to
`USER factory` before the entrypoint. The uid is fixed and deliberately does **not** attempt to
match any host uid — this is not the UID/GID-matches-the-host-mount concern the prior change's
Non-goals explicitly deferred to production; it satisfies only "not root," which is all
`bypassPermissions` actually requires.

Git identity and `safe.directory` configuration move from `--global` (which writes to root's
`$HOME`, unreachable once the process is no longer root) to `--system` (`/etc/gitconfig`, one file,
applies regardless of which user runs the container) so the platform's own commit identity
(`turn.py::PLATFORM_CO_AUTHOR`, ADR-0004) still resolves after the user switch. `HOME` itself is
not hardcoded in the image for this reason: `docker-entrypoint.sh` derives it at runtime via
`getent passwd "$(id -u)"`, so a future uid change has one place to edit (the `Dockerfile`'s
`useradd` line), not two.

## Consequences

- `bypassPermissions` now succeeds for the container's unattended turns; the two structurally
  failed $0 turns that surfaced this are the receipt.
- The venv, built as root during the image's dependency-install layers (`uv sync`'s own caching
  wants that), is explicitly `chown -R factory:factory` before the `USER factory` switch — a step
  that would silently break `uv run` inside the running container if dropped.
- **Not** a solution to host-mount uid matching. A future production topology that bind-mounts a
  host directory owned by a specific uid may still need to reconcile with it; this decision is
  scoped to "not root," nothing more, and says so.

## References

- `Dockerfile` — `useradd`, `git config --system`, `USER factory`.
- `docker-entrypoint.sh` — `HOME` derivation via `getent passwd`.
- Commit `5df739d` ("run-the-loop-inside-the-container: run as a fixed non-root user") — carries
  the measured binary error verbatim.
- `openspec/changes/archive/2026-08-20-run-the-loop-inside-the-container/design.md` (D2, D3).
