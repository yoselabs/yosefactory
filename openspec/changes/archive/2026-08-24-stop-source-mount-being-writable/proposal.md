## Why

[[S245]] (K project 160, cluster C6): `docker-compose.yml` mounts the machine's own source at
`/app` alongside the loop's queue/workspace at `/data/workspace`. An unattended planning turn read
`/app`, invented two backlog items about the factory itself (not about the workspace it was given),
and a following turn spent $6.67 running a full OpenSpec cycle **inside `/app`** — branch
`sweep-blocked-and-snoozed-deadlines`, three commits, 935 insertions across 11 files including
`runtime/turn.py` and `protocol/backlog.py` — and left the repository checked out on that branch.
The next worker dispatched into the tree started from it, unknowingly, until stopped.

D025 and the CI credential fencing hold for the *credential* (demonstrated with a hostile fixture).
They do not hold for the *source*: a bind mount that exists for developer convenience gave an
unattended turn commit access to the platform running it. Nothing in the topology said an agent's
writes stop at the workspace boundary — only the workspace's own directory structure implied it,
and nothing enforced the implication.

## What Changes

- `docker-compose.yml`'s source mount becomes `./:/app:ro`. The workspace mount
  (`./.dev-workspace:/data/workspace`) is unchanged — this is where a turn is meant to write.
- `Dockerfile` sets `RUFF_CACHE_DIR` and `PYTEST_ADDOPTS` so `ruff` and `pytest` do not need to
  write into `/app` to run; both tools already degrade silently (no `.pyc`/`__pycache__` write
  errors observed) except these two cache paths, measured directly against the built image.
- `docker-entrypoint.sh` refuses to start `yosefactory-loop` / `yosefactory-loop-scheduled` if the
  source root (`$YF_SOURCE_ROOT`, default `/app`) is writable — a live check for the boundary this
  change declares, so a future compose edit that silently reintroduces a writable mount fails loud
  at container start instead of failing silent until the next incident (the S195 pattern named in
  `orchestration.md`).
- ADR recording why read-only-mount was chosen over dropping the mount entirely or a uid-based
  write guard.

## Capabilities

### Modified Capabilities
- `containerized-loop/dev-and-production`: the development compose configuration's source mount is
  read-only, and the loop's entrypoint asserts this at startup for the two turn-running commands.

## Impact

- `docker-compose.yml` — source mount gains `:ro`.
- `Dockerfile` — `RUFF_CACHE_DIR`, `PYTEST_ADDOPTS` env vars.
- `docker-entrypoint.sh` — write-guard check before the existing token check.
- `tests/scripts/test_entrypoint_write_guard.py` — new, drives the real script.
- `decisions/0017-*.md` — new ADR.
- No source code under `src/yosefactory/` changes; `main(unattended=False)` and
  `main(unattended=True)` are both untouched — the fix is topology plus one shell-level assertion.

## Non-goals

- Production posture (dropping the mount, running the built image as-is) — `docker-compose.yml`'s
  own header already names this as the production alternative; not built here, this change keeps
  the dev loop live-editable.
- UID/GID-based write denial (ADR-0007's non-root uid is unrelated to source-mount writability;
  considered and rejected below, see `design.md`).
- Detecting or reverting a commit already made through the leaked mount
  (`sweep-blocked-and-snoozed-deadlines`) — that branch is out of scope, preserved unmerged per
  [[D002]], for the director/Denis to dispose of.
