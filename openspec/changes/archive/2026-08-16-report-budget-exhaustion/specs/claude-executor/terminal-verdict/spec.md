# claude-executor/terminal-verdict Specification

## ADDED Requirements

### Requirement: Budget exhaustion is its own outcome

A run that ends because it exhausted a spending limit SHALL be classified as budget exhaustion,
carrying no failure kind, and SHALL NOT be classified as a task error or as a generic failure.

The classification SHALL be read from the structured fields the agent emits to report the stop, and
SHALL be recognised from either of them when the executor reports it under more than one name.

**Reason, carried with the rule:** a starved run and a broken one have opposite fixes, and this is
the same distinction quota exhaustion already has its own outcome for. A wrong kind is worse than an
absent one here — an absent kind invites the question, and `task_error` answers it in the direction
that sends a person to debug a factory that only ran out of money. Nothing downstream can recover the
distinction once it is lost, so a faithful record of a wrong classification is a faithful record of a
falsehood.

#### Scenario: An exhausted budget is not a task error
- **WHEN** a run emits a terminal event reporting that its spending limit was reached
- **THEN** the outcome is budget exhaustion and no failure kind is assigned

#### Scenario: Either reported name is recognised
- **WHEN** the executor names the stop in one structured field but not the other
- **THEN** the outcome is still budget exhaustion

#### Scenario: A completed run is unaffected
- **WHEN** a run emits a terminal event reporting normal completion
- **THEN** the outcome is success
