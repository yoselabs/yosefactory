# turn-loop Specification

## Purpose
`run_loop` optionally drives a `BoardAdapter` — ingesting commands and projecting turn results —
without adding any path from a board read to an executor invocation.

## ADDED Requirements

### Requirement: Board ingestion never invokes an executor

When `run_loop` is configured with a `BoardConfig`, it SHALL apply unconsumed board commands
(`board.inbox.ingest()`) purely as git writes. No code path from a board poll to
`runtime.turn.take_turn` or to an `Executor` call SHALL exist. A board command's effect on which
turn runs next SHALL be mediated only by the existing `EXTERNAL_EVENT` wake condition observing
the queue's own `HEAD`.

#### Scenario: An applied board command does not itself start an executor
- **WHEN** the loop's board poll finds and applies one or more unconsumed commands
- **THEN** no `Executor` call happens as a direct consequence of that poll
- **AND** the loop only calls `take_turn` when one of the three existing wake conditions fires

#### Scenario: An idle board (nothing to ingest) costs the same as no board at all
- **WHEN** a board poll finds no unconsumed events
- **THEN** no git write occurs, `HEAD` does not move, and no wake condition is affected by the poll

### Requirement: Board polling runs at its own cadence, independent of wake polling

`BoardConfig.poll_seconds` SHALL govern how often the loop polls the board, and this interval
SHALL be independent of `WakeConfig.poll_seconds` and `WakeConfig.heartbeat_seconds`. `BoardConfig`
SHALL refuse construction with a non-positive `poll_seconds`.

#### Scenario: The board is not polled on every wake-loop tick
- **WHEN** `WakeConfig.poll_seconds` is smaller than `BoardConfig.poll_seconds`
- **THEN** the loop's cheap local wake checks (ready item, `HEAD`) still run on every tick
- **AND** the board is polled only after its own, longer interval has elapsed

#### Scenario: A non-positive board poll interval is refused
- **WHEN** `BoardConfig` is constructed with `poll_seconds <= 0`
- **THEN** construction raises before the loop runs

### Requirement: A completed turn's result is projected back to the board

When `run_loop` is configured with a `BoardConfig`, it SHALL call `board.projection.project_all`
once before the first turn and once after every `take_turn` call, regardless of that turn's
outcome.

#### Scenario: The board reflects pre-existing queue state before the loop's first turn
- **WHEN** `run_loop` starts with a `BoardConfig` and the queue already contains items
- **THEN** those items are projected to the board before the first turn runs

#### Scenario: Every turn's outcome reaches the board, not only successful ones
- **WHEN** a turn completes with any outcome (`advanced`, `blocked`, `failed`, `nothing-ready`)
- **THEN** `project_all` runs again immediately after, reflecting the queue's current state
