## ADDED Requirements

### Requirement: The factory builds and runs as a Docker image

The repository SHALL provide a `Dockerfile` that builds an image containing `uv`, the `claude`
binary pinned to `executor.claude.PINNED_VERSION`, and the `yosefactory` package installed such
that `yosefactory-loop` and `yosefactory-loop-scheduled` are runnable inside the built image
without further setup.

#### Scenario: The image builds and the pinned binary is reachable inside it
- **WHEN** the `Dockerfile` is built
- **THEN** `claude --version` inside a container from that image reports
  `executor.claude.PINNED_VERSION`, and `yosefactory-loop-scheduled --help` exits `0`

### Requirement: A development compose configuration bind-mounts source without requiring a rebuild

The repository SHALL provide a `docker-compose.yml` whose default service bind-mounts the
repository's source tree into the container such that a change to a `.py` file under `src/` takes
effect on the next command run inside the container, without an image rebuild. The virtual
environment SHALL be located outside the bind-mounted path so the mount cannot shadow it.

#### Scenario: A source edit is visible without a rebuild
- **WHEN** a file under `src/yosefactory/` is edited on the host after the container has been
  built and started
- **THEN** running a command inside the running container that imports the edited module observes
  the edit, with no `docker build` or `docker compose build` between the edit and the check

#### Scenario: The bind mount does not shadow the virtualenv
- **WHEN** the container starts with the source bind-mounted
- **THEN** `uv run python -c "import yosefactory"` succeeds inside the container without
  triggering a fresh `uv sync`

### Requirement: The loop's queue/workspace mount is separate from the source mount by default

The default `docker-compose.yml` configuration SHALL NOT point the loop's `Places.local` target at
the same path as the bind-mounted source tree. `run_loop` SHALL additionally refuse to start (a
clear error, before any turn runs) if the path it is given as `places.workspace` has uncommitted
changes at the moment it is invoked.

**Reason, carried with the rule:** a bind mount that makes source edits live is, by construction,
the same mechanism that lets a running loop and a human editor race on the same files — measured
directly under `add-scheduled-loop`'s `launchd` receipt, where `take_turn`'s commit collided with
`prek`'s tree-wide stash against a dirty checkout. The default configuration is what people
actually run; the guard is the fallback for when the separation is bypassed anyway.

#### Scenario: The default compose configuration keeps the two mounts apart
- **WHEN** `docker-compose.yml`'s default service is inspected
- **THEN** the source bind mount's target path and the value passed as the loop's `repo` argument
  are different paths

#### Scenario: A dirty workspace refuses the loop before any turn runs
- **WHEN** `run_loop` (or an entrypoint built on it) is invoked with `places.workspace` pointing at
  a git working tree that has uncommitted changes
- **THEN** it raises before calling `take_turn`, with a message naming the dirty path, and no
  ledger record is written for that invocation

#### Scenario: A clean workspace is unaffected
- **WHEN** `places.workspace` has no uncommitted changes at startup
- **THEN** the loop starts normally, exactly as before this change

### Requirement: Container auth is `CLAUDE_CODE_OAUTH_TOKEN`, supplied at run time, never committed or baked in

The container SHALL authenticate `claude` using `CLAUDE_CODE_OAUTH_TOKEN` read from the process
environment at run time. Neither the `Dockerfile` nor `docker-compose.yml` SHALL contain a literal
credential value. The repository SHALL provide `.env.example` naming the variable with an empty
value and a comment stating it is produced by `claude setup-token`. The container's entrypoint
SHALL check that `CLAUDE_CODE_OAUTH_TOKEN` is set and non-empty before invoking the loop, and SHALL
exit with a message naming the missing variable — never the variable's value — if it is not.

#### Scenario: A missing token fails fast and by name
- **WHEN** the container starts with `CLAUDE_CODE_OAUTH_TOKEN` unset or empty
- **THEN** it exits before invoking `yosefactory-loop-scheduled`, printing a message that names
  `CLAUDE_CODE_OAUTH_TOKEN` as missing and never prints the variable's value (because it has none)

#### Scenario: No credential value appears in any committed file
- **WHEN** every file this change adds to the repository is inspected
- **THEN** none contains a literal token, API key, or other credential-shaped string; `.env.example`
  contains only the variable name, an empty value, and a provenance comment

### Requirement: Quota exhaustion is legible as its own outcome, not a generic failure

A container-run turn that stops because the `CLAUDE_CODE_OAUTH_TOKEN` subscription's quota is
exhausted SHALL be recorded with `RunOutcome.FAILED` and `FailureKind.RATE_LIMIT` (or, for a
per-turn budget ceiling, `RunOutcome.BUDGET_EXHAUSTED`), distinguishable on disk from a crash
(`FailureKind.CRASH`) or an ordinary task failure (`FailureKind.TASK_ERROR`).

**Reason, carried with the rule:** a subscription token cannot run away in dollars, but it can
exhaust the same quota Denis uses interactively, and a loop that hits that limit unattended is
indistinguishable from a broken factory unless the record says which one happened.

#### Scenario: A rate-limited stream is recorded distinctly, not as a generic failure
- **WHEN** the executor's stream reports a `rate_limit_event`, or the underlying API responds with
  status `429`
- **THEN** the resulting `RunResult.failure_kind` is `FailureKind.RATE_LIMIT`, never
  `FailureKind.TASK_ERROR` or `None`

#### Scenario: Spend-ceiling figures are numbers and a rate signal, not an invoice, under a
subscription token
- **WHEN** `ledger/spend.jsonl` records cost for a turn run inside the container under
  `CLAUDE_CODE_OAUTH_TOKEN`
- **THEN** the recorded `total_cost_usd` is the value the binary itself reports (unchanged
  plumbing), and `--spend-ceiling-usd` continues to bound the loop as before — but no invoice is
  implied by either figure

### Requirement: A container-run turn leaves a record readable from the host

Running the loop inside a container against a mounted queue/workspace path SHALL produce
`ledger/runs/*.json` and (when applicable) `.wake.json` records under that mounted path, readable
from the host filesystem after the container process exits or between invocations, without any
process from the container still running.

#### Scenario: A ledger record is readable from outside the container
- **WHEN** a turn completes inside the container against a bind-mounted or volume-mounted
  queue/workspace path
- **THEN** the corresponding `ledger/runs/*.json` record is readable from the host at the mounted
  path, with no container process required to read it
