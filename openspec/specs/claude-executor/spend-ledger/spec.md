# claude-executor/spend-ledger Specification

## Purpose
Every real invocation of the pinned binary costs money the moment it runs, whether the caller is a
test with a `tmp_path` workspace that pytest deletes on teardown, a foreign production workspace this
platform does not own, or the real queue. Before this capability, that cost was never recorded
anywhere durable for any of the three — this closes that gap for all of them, not only for tests.

**Whose ledger this is.** The spend log resolves into yosefactory's own checkout regardless of which
workspace the invocation ran against. Spend belongs to the platform that paid for the call, not to
the repository the call happened to be working on.
## Requirements
### Requirement: Every completed invocation appends a durable spend row

`runtime/turn.py::_finish` SHALL append one row to a spend ledger for every turn that invoked an
`Executor`, reading `total_cost_usd` from that invocation's `RunResult.usage` regardless of which
`Executor` produced it — this requirement is not specific to `executor/claude.py::run()`. The row
SHALL be written at a path resolved from `turn.spend_log_for(places)` (`places.ledger.parent /
"spend.jsonl"`, inside `places.queue`), and SHALL be included in the same `commit()` call that
stages the turn's own run record — never left for a later, unrelated commit to sweep up.

Each row SHALL carry: a timestamp, the `run_id`, and `total_cost_usd` (zero is a real value, not an
omission — the row is written even when cost is `0.0`).

**`run_id` is the join key, not an incidental field.** It is the same id the matching `TurnRecord`
in `ledger/runs/` is named for. A spend row without it is an orphan number; with it, a reader can
ask what one specific turn cost, not only what a whole day cost.

**Reason, carried with the rule:** a test's `runs_dir` is routinely a `tmp_path` fixture, deleted at
teardown, and a production `runs_dir` may belong to a foreign workspace this platform does not own.
A cost figure that exists only inside either is unrecoverable once the caller's own lifecycle ends.
Writing from the turn rather than the executor closes a second, independent version of the same
problem: a row written by the executor, at a path resolved from the package's own install location,
could exist durably and still never be reachable by the one function (`turn.commit()`, ADR-0004)
that is allowed to stage it into `places.queue` — a real defect, found live (yoselabs/factory-state
Actions run 32571722314, 2026-08-22), not a hypothetical this requirement is guarding against
speculatively.

**`runtime.spend.SPEND_LOG`'s package-relative default is retained, narrowed.** It resolves by
walking up from `spend.py`'s own `__file__` to the nearest `pyproject.toml`/`.git`, and remains the
default for `spend.record`/`spend.total_since` when no `Places` is in view — a direct import, a
REPL, or this package's own `make test-live` session receipt, where "the platform's own checkout"
and "the repository being worked" are the same directory by construction. It is no longer what any
caller running a real turn passes; `spend_log_for(places)` is.

#### Scenario: A run with real cost records a matching row

- **WHEN** a turn's `Executor` invocation completes with a `RunResult` reporting `total_cost_usd > 0`
- **THEN** the spend ledger at `spend_log_for(places)` gains exactly one new row
- **AND** that row's `total_cost_usd` matches the `RunResult`'s value
- **AND** that row's `run_id` matches the turn's `run_id`
- **AND** that row is present in the same commit as the turn's own run record

#### Scenario: The row survives the caller's own workspace being deleted

- **WHEN** a turn runs against a `runs_dir` inside a directory that is deleted immediately after the
  turn returns
- **THEN** the spend ledger row written for that turn is still present and readable afterward, at
  its fixed path inside `places.queue`, independent of the deleted `runs_dir`

#### Scenario: The writer is the turn, not any particular executor

- **WHEN** a turn runs an `Executor` other than `executor/claude.py::run()`
- **THEN** the spend row is still written, because `runtime/turn.py::_finish` — not the executor —
  is what writes it

### Requirement: The ledger is append-only and independently readable

The spend ledger SHALL be a plain, append-only, line-delimited file that any reader can sum without
importing this codebase or invoking any other module.

**Reason, carried with the rule:** "what did today cost" must be answerable by `tail`, `grep`, or a
one-line script — a durable record that requires this repository's own code to interpret is not
meaningfully more durable than the transcript it replaces.

#### Scenario: A day's total is computable by filtering rows on their timestamp

- **WHEN** two or more rows exist with different timestamps
- **THEN** filtering the file's lines by a timestamp threshold and summing `total_cost_usd` across
  the remainder yields the correct total for that window, using only the file's own contents

