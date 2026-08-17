## Purpose

Every real invocation of the pinned binary costs money the moment it runs, whether the caller is a
test with a `tmp_path` workspace that pytest deletes on teardown, a foreign production workspace this
platform does not own, or the real queue. Before this capability, that cost was never recorded
anywhere durable for any of the three — this closes that gap for all of them, not only for tests.

**Whose ledger this is.** The spend log resolves into yosefactory's own checkout regardless of which
workspace the invocation ran against. Spend belongs to the platform that paid for the call, not to
the repository the call happened to be working on.

## ADDED Requirements

### Requirement: Every completed invocation appends a durable spend row

`executor/claude.py::run()` SHALL append one row to a spend ledger after every invocation that
reaches a terminal event, at a path resolved from this module's own location — never from a
caller-supplied `runs_dir` or workspace, since either may be ephemeral.

Each row SHALL carry: a timestamp, the `run_id`, and `total_cost_usd` as reported by the terminal
event (zero is a real value, not an omission — the row is written even when cost is `0.0`).

**`run_id` is the join key, not an incidental field.** It is the same id the matching `TurnRecord`
in `ledger/runs/` is named for. A spend row without it is an orphan number; with it, a reader can
ask what one specific turn cost, not only what a whole day cost.

**Reason, carried with the rule:** a test's `runs_dir` is routinely a `tmp_path` fixture, deleted at
teardown, and a production `runs_dir` may belong to a foreign workspace this platform does not own.
A cost figure that exists only inside either is unrecoverable once the caller's own lifecycle ends —
this was true of every run before this capability existed, not only tests, measured against one
archived change whose true spend is now permanently unknowable.

**The path resolution has a known limitation, carried forward rather than newly introduced.**
`SPEND_LOG` is resolved by walking up from this module's own `__file__`, the same pattern
`protocol/backlog.py`'s `VOCABULARY_SPEC` uses. It assumes yosefactory runs from its own checkout;
if that stops being true, both call sites break the same way, silently.

#### Scenario: A run with real cost records a matching row

- **WHEN** an invocation of `run()` completes with a terminal event reporting `total_cost_usd > 0`
- **THEN** the spend ledger gains exactly one new row
- **AND** that row's `total_cost_usd` matches the terminal event's value
- **AND** that row's `run_id` matches the invocation's `run_id`

#### Scenario: The row survives the caller's own workspace being deleted

- **WHEN** an invocation of `run()` is given a `runs_dir` inside a directory that is deleted
  immediately after the call returns
- **THEN** the spend ledger row written for that invocation is still present and readable
  afterward, at its fixed path independent of the deleted directory

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
