# claude-executor/cost-ceiling Specification

## Purpose
Lets a caller request a dollar ceiling on one run, and states plainly what the binary actually
enforces when that ceiling is set — a post-turn detector, not a preventive bound.
## Requirements
### Requirement: A cost ceiling is optional and additive

The executor's caller MAY supply a dollar ceiling for a run. When absent, the executor SHALL invoke
the binary exactly as it would with no ceiling at all — no flag, no default substituted on the
caller's behalf.

**Reason, carried with the rule:** a silently substituted default would make an unbounded run bounded
without anyone having asked for it, which is a behaviour change disguised as a bug fix.

#### Scenario: No ceiling supplied, no flag sent

- **WHEN** a run is invoked with no cost ceiling
- **THEN** the invocation carries no budget flag
- **AND** the run is unbounded by cost exactly as it was before this capability existed

#### Scenario: A ceiling supplied is sent verbatim

- **WHEN** a run is invoked with a cost ceiling of `$0.02`
- **THEN** the invocation requests that ceiling from the binary

### Requirement: The ceiling is a detector, not a preventive bound

The executor SHALL NOT describe or document a supplied cost ceiling as a guarantee that a run's spend
stays under it. The binary evaluates the ceiling after a turn completes and stops the **next** turn
from starting; it does not interrupt the turn that crosses the line.

**Reason, carried with the rule, and it is measured rather than assumed:** a run capped at `$0.02` was
observed spending `$0.048` before the stop fired — 2.4× the requested ceiling, in a single turn whose
own cost exceeded the entire budget. A caller that reads "ceiling" as "hard limit" will size a budget
assuming the worst case is the ceiling itself, and the worst case is unbounded by the size of one
turn.

#### Scenario: A single expensive turn exceeds the ceiling that named it

- **WHEN** a run is invoked with a cost ceiling, and one turn's own cost exceeds that ceiling before
  the turn completes
- **THEN** that turn is allowed to finish
- **AND** the stop, if any, is observed only on the turn after it

#### Scenario: The documentation does not claim prevention

- **WHEN** the cost ceiling capability is described anywhere in this codebase
- **THEN** the description states that it detects and stops the next turn
- **AND** it does not state or imply that spend is bounded to the ceiling

### Requirement: This capability names one argument and no others

Wiring the cost ceiling SHALL NOT be read as a claim about any other unwired capability. In
particular, a turn-count limit remains unavailable at the pinned version and is unaffected by this
capability's existence.

**Reason, carried with the rule:** two capabilities sharing a module and a table invites the
assumption that fixing one fixed both. Nothing here changes what `EMULATED` still correctly declares.

#### Scenario: Wiring the cost ceiling implies nothing about the turn ceiling

- **WHEN** a caller supplies a cost ceiling
- **THEN** no turn-count flag is sent, because none exists to send
- **AND** the turn ceiling remains enforced only by the harness, as before this capability

