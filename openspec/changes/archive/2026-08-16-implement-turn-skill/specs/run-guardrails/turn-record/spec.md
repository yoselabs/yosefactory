## MODIFIED Requirements

### Requirement: Two writers, and the record says which

A turn record MAY be authored either by the agent that performed the run or by the
supervisor that governed it. Every record SHALL carry `enforced_by` with the value `agent`
or `harness` identifying its author.

The supervisor SHALL author a record whenever the agent cannot: a wall-clock or
turn-ceiling stop terminates the agent process, so the terminated process writes nothing.
A supervisor-authored record for such a stop SHALL carry `outcome: failed` and
`enforced_by: harness`.

**Authoring is not persisting.** The supervisor SHALL return the record it authored and
SHALL NOT append it to the stream unless the caller supplies somewhere to put it. Exactly
one component SHALL write the row for a turn, and it is the component that knows the turn
happened — a supervisor governs one invocation, and a turn may contain none.

**Reason, carried with the rule:** without `enforced_by`, a run killed by the harness is
indistinguishable from a run that failed honestly, and the two demand different responses.
And a turn that finds nothing eligible starts no process at all, so a supervisor that never
ran cannot write the `nothing-ready` row that turn still owes — the row this capability most
needs, because it is what distinguishes an idle factory from a stalled one. A supervisor
that wrote its own row as well would not merely duplicate: the two rows answer different
questions, one about a process and one about a turn.

#### Scenario: A harness kill still produces a record
- **WHEN** the supervisor terminates an agent for exceeding its wall clock
- **AND** the caller supplied somewhere for the record to go
- **THEN** a record is appended carrying `outcome: failed` and `enforced_by: harness`

#### Scenario: An agent verdict is marked as its own
- **WHEN** an agent completes and writes its own verdict
- **THEN** the record carries `enforced_by: agent`

#### Scenario: A governed run with nowhere to write leaves the stream untouched
- **WHEN** a caller governs a run without supplying anywhere to record it
- **THEN** the authored record is returned to the caller
- **AND** no marker and no record appear in the stream

#### Scenario: A turn that runs no agent still owes its row
- **WHEN** a turn finds nothing eligible and starts no process
- **THEN** a record carrying `outcome: nothing-ready` is written for that turn
