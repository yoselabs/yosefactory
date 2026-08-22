## Purpose

Lets the shipped entrypoint (`yosefactory-loop` / `yosefactory-loop-scheduled`) run a turn whose
queue and workspace are different repositories, name a foreign workspace's own test command, and
bound a single turn's spend independently of the loop's cumulative ceiling — the union of what a
hand-written cross-repo driver otherwise has to build outside this repository.

## ADDED Requirements

### Requirement: The entrypoint accepts separate queue and workspace roots

`main` (and therefore `scheduled_main`) SHALL accept `--queue` and `--workspace`, each an optional
path. Omitted, each SHALL default to the existing `repo` positional argument. When `--queue` and
`--workspace` resolve to the same path, the `Places` built SHALL be identical to what
`Places.local(repo)` builds today, including a single shared lock file for both roles. When they
resolve to different paths, `workspace_lock` SHALL be keyed to the workspace's own path
(`workspace/.git/yosefactory-turn.lock`), not to the queue.

**Reason, carried with the rule:** `Places` has addressed queue and workspace separately since
`turn-places`; nothing before this exposed it past an import. A caller with a queue in one
repository and a workspace in another (`yoselabs/factory-state`'s split, K D026) could not reach
the entrypoint at all and had to construct `Places` itself.

#### Scenario: Omitting both flags reproduces today's collapsed behavior
- **WHEN** the entrypoint is invoked with neither `--queue` nor `--workspace`
- **THEN** both resolve to the `repo` positional, and the resulting `Places` matches
  `Places.local(repo)` field for field

#### Scenario: A split queue and workspace are both honored
- **WHEN** the entrypoint is invoked with `--queue` pointing at one git repository and
  `--workspace` pointing at a different one
- **THEN** the turn reads its backlog and writes its ledger under the queue path, and the agent's
  working directory, test command, dirty-check, and commit all act on the workspace path

#### Scenario: A split workspace gets its own lock, not the queue's
- **WHEN** `--queue` and `--workspace` resolve to different paths
- **THEN** the constructed `Places.workspace_lock` is `<workspace>/.git/yosefactory-turn.lock`,
  independent of `Places.queue_lock`

### Requirement: The entrypoint can name a foreign workspace's own test command

`main` SHALL accept `--test-command`, a space-separated string overriding the built-in
`DEFAULT_TEST_COMMAND` (`pytest -q`) that is otherwise hard-coded with no way to change it. When
omitted, behavior SHALL be unchanged.

**Reason, carried with the rule:** a workspace's own verification gate is not always `pytest -q` —
a2web's is `make check`. An entrypoint that cannot name the foreign repository's gate cannot
verify a turn against it at all.

#### Scenario: A custom test command reaches the verification gate
- **WHEN** the entrypoint is invoked with `--test-command "make check"`
- **THEN** the turn's verification gate runs `make check` in the workspace, not `pytest -q`

#### Scenario: Omitting the flag keeps the existing default
- **WHEN** the entrypoint is invoked without `--test-command`
- **THEN** the turn's verification gate runs `DEFAULT_TEST_COMMAND` exactly as before this change

### Requirement: A per-turn cost ceiling is settable independently of the loop's cumulative spend ceiling

`main` SHALL accept `--cost-ceiling-usd`, feeding `Guardrails.cost_ceiling_usd` (the executor's
post-turn budget detector for one turn). This flag SHALL be distinct from the existing
`--spend-ceiling-usd`, which feeds `LoopBound.spend_ceiling_usd` (the loop's cumulative ceiling
across iterations) and is unchanged by this requirement. Both MAY be given on the same invocation
and SHALL be applied independently — neither substitutes for the other.

**Reason, carried with the rule:** these are different quantities that share a unit and a shape,
which is exactly how they get confused. `main` today constructs `Guardrails` with no
`cost_ceiling_usd` at all, so a turn is bounded only by wall clock; a hand-written driver had to
set one by hand to avoid an unbounded single turn.

#### Scenario: A per-turn ceiling is passed to Guardrails, not to the loop bound
- **WHEN** the entrypoint is invoked with `--cost-ceiling-usd 2.00`
- **THEN** the `Guardrails` passed to `take_turn` has `cost_ceiling_usd == 2.00`
- **AND** `LoopBound.spend_ceiling_usd` is unaffected by this flag and reflects only
  `--spend-ceiling-usd`, if given

#### Scenario: Omitting the flag keeps a turn unbounded by cost, as today
- **WHEN** the entrypoint is invoked without `--cost-ceiling-usd`
- **THEN** `Guardrails.cost_ceiling_usd` is `None`, exactly as `main` constructs it today

### Requirement: A single cross-repo turn is expressible without a dedicated one-shot mode

The existing `--max-iterations 1` SHALL be sufficient, combined with `--queue`/`--workspace`, to
run exactly one turn against a split queue and workspace and stop — no additional flag or mode is
required for this case.

**Reason, carried with the rule:** `run_loop`'s first iteration always fires immediately
(`WakeReason.STARTUP`, no wait), so one iteration already behaves as a single unattended turn. A
CI job that fires on its own external trigger (D024 ruling 1: "the job's trigger is the wake")
needs exactly this, not a new code path.

#### Scenario: max-iterations=1 against a split queue/workspace runs one turn and stops
- **WHEN** the entrypoint is invoked with `--max-iterations 1`, `--queue`, and `--workspace`
- **THEN** exactly one call to `take_turn` is made, against the given queue and workspace, and the
  process exits without waiting on any wake condition beyond the immediate startup one
