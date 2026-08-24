# containerized-loop/dev-and-production Specification

## MODIFIED Requirements

### Requirement: A development compose configuration bind-mounts source without requiring a rebuild

The repository SHALL provide a `docker-compose.yml` whose default service bind-mounts the
repository's source tree into the container such that a change to a `.py` file under `src/` takes
effect on the next command run inside the container, without an image rebuild. The virtual
environment SHALL be located outside the bind-mounted path so the mount cannot shadow it. **The
source bind mount SHALL be read-only** — no process running inside the container SHALL be able to
write to the mounted source tree, regardless of what that process decides to do. The image SHALL
configure `ruff` and `pytest` (via `RUFF_CACHE_DIR` and `PYTEST_ADDOPTS`) to keep their cache
writes outside the read-only mount, so `make check` still passes unmodified inside the container.

**Reason, carried with the rule:** [[S245]] measured that a writable source mount gave an
unattended turn commit access to the platform running it — not a hostile fixture, an ordinary
planning turn that found `/app` more interesting than the workspace it was given. The bind mount
existed for developer convenience (live-editable source); nothing about that purpose requires the
mount to also be writable *from inside the container*. A developer edits the host copy with their
own editor, which the container never mediates.

#### Scenario: A source edit is visible without a rebuild

- **WHEN** a file under `src/yosefactory/` is edited on the host after the container has been
  built and started
- **THEN** running a command inside the running container that imports the edited module observes
  the edit, with no `docker build` or `docker compose build` between the edit and the check

#### Scenario: The bind mount does not shadow the virtualenv

- **WHEN** the container starts with the source bind-mounted
- **THEN** `uv run python -c "import yosefactory"` succeeds inside the container without
  triggering a fresh `uv sync`

#### Scenario: Nothing inside the container can write to the mounted source

- **WHEN** any process inside the container attempts to write, create, or delete a file under the
  mounted source path (`/app`)
- **THEN** the filesystem refuses the write (a read-only-filesystem error), regardless of the
  writing process's identity, arguments, or intent

#### Scenario: `make check` passes inside the container despite the read-only mount

- **WHEN** `make check` (`lint ty test citations`) is run inside a container built from this
  image, with the source mounted `:ro`
- **THEN** `lint` (`ruff check`), `ty`, and `test` (`pytest -q`) all pass, and `citations` runs to
  completion (skipping cleanly if no K checkout is present, which is expected inside a container)

## ADDED Requirements

### Requirement: The entrypoint refuses to start a turn if the source mount is writable

`docker-entrypoint.sh` SHALL check, for the two turn-running commands
(`yosefactory-loop`, `yosefactory-loop-scheduled`), whether the source root
(`$YF_SOURCE_ROOT`, defaulting to `/app`) is writable, and SHALL refuse to start — exiting non-zero
with a message naming the path — if it is. This check SHALL run before any turn is invoked, so a
regression in the compose/mount configuration is caught at container start rather than discovered
after an unattended turn has already run.

**Reason, carried with the rule:** a `:ro` flag in a YAML file is a declared boundary with no live
check on it — the exact pattern the corpus already names as failure-prone (a mechanism that looks
enforced but isn't). This requirement converts the boundary into something that fails loudly the
moment it stops holding, rather than staying silent until the next S245-shaped incident.

#### Scenario: A writable source root refuses to start

- **WHEN** `docker-entrypoint.sh` is invoked with `yosefactory-loop-scheduled` (or
  `yosefactory-loop`) as its command, and `$YF_SOURCE_ROOT` (or `/app`, if unset) is writable
- **THEN** the entrypoint exits non-zero before invoking the command, with a message naming the
  writable path

#### Scenario: A read-only source root starts normally

- **WHEN** `docker-entrypoint.sh` is invoked the same way and the source root is read-only
- **THEN** the entrypoint proceeds past the guard (subject to the existing token check) exactly as
  before this change

#### Scenario: Diagnostic commands are unaffected

- **WHEN** `docker-entrypoint.sh` is invoked with a command other than `yosefactory-loop` or
  `yosefactory-loop-scheduled` (for example `claude --version`, a shell, or a diagnostic script)
- **THEN** the write-guard check does not run, and the command executes exactly as before this
  change
