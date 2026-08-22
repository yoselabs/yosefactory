## Why

Found live: yoselabs/factory-state Actions run 32571722314 (2026-08-22). Three jobs green, the
ledger's run record committed and pushed, and `ledger/spend.jsonl` did not exist in the repository
afterwards — the only surviving record of the run's $0.2583899 was a CI log with 90-day retention.

**Root cause, confirmed against disk before designing (Article XII).** Two separate defects, not
one:

1. `executor/claude.py::run()` called `runtime.spend.record()` with no `log_path` override, so it
   wrote to `runtime.spend.SPEND_LOG` — resolved via `paths.repo_root()` from `spend.py`'s own
   `__file__`, i.e. wherever this package is *installed*. `runtime/turn.py::commit()`, the only
   function that ever composes a git commit here (ADR-0004), commits explicit pathspecs inside
   `places.queue` — the repository `take_turn` was actually pointed at. Under `run-the-loop-inside-
   the-container`'s topology (`docker-compose.yml`: source at `/app`, the loop's queue+workspace at
   a separate bind mount) these are two different directories. A row written to one can never be
   staged by a `commit()` call scoped to the other — not a race, a structural impossibility.
2. Even had the row landed in the right repository, nothing ever named its path in `commit()`'s
   pathspec list. `git commit -- <paths>` (Article V) stages only what it is told; a file sitting
   next to the paths named is invisible to it by design.

No promotion entity from K project 160 names this defect — it is a build-time finding
(`commit-attribution`'s own scope never covered spend, and `run-guardrails/turn-record` predates
`Places` having a queue distinct from the package's own checkout). Dispatched directly by the
director against the CI receipt above; the finding itself is worth a P160 write-back at close
(build-loop.md's "During" trigger 1 — a mechanism that will not build as specified: `SPEND_LOG`'s
"spend belongs to the platform" reasoning was designed before `Places` could split queue from
package location, and this change is exactly where it stops holding).

## What Changes

- **`runtime/turn.py`** becomes the sole writer of the spend row. `_dispose` no longer needs to —
  every branch (`failed`, `blocked`, the planning return, the normal return) now threads
  `result.usage.total_cost_usd` into `_finish`, which is the one place that already writes the run
  record and calls `commit()`. `_finish` writes the spend row (via `runtime.spend.record`, given an
  explicit `log_path`) and folds its path into the same `commit()` call that stages the run record —
  one `git add` + one `git commit`, so the two either both land or neither does.
- **New `turn.spend_log_for(places) -> Path`**: `places.ledger.parent / "spend.jsonl"` — a sibling
  of `ledger/runs/`, inside `places.queue`, never resolved from the package's own install location.
  Exported so `runtime.loop.run_loop`'s own spend-ceiling check (`spend.total_since`) can point at
  the same file `take_turn` actually writes, instead of silently reading a different one.
- **`executor/claude.py`** drops its own `spend.record()` call and the import it needed for it.
  Recording moves to `turn.py` so it applies uniformly to every `Executor`, not only the real one —
  the existing `FakeExecutor`-based integration suite exercises the commit-time guarantee for free,
  with no changes to the fixture.
- **Ordering, the part that is not obvious.** `_finish` computes the turn's `dirty` flag and writes
  the spend row *after* it, and every call into `_finish` happens strictly after any gate this
  turn's event required (`verify.may_write_done` demands a clean `places.workspace` before a `done`
  proposal can pass). Both orderings exist for the same reason: under `Places.local` (today's only
  configuration, and every test fixture), `places.queue` and `places.workspace` are the same
  directory, so a write made before the gate or before `dirty` is computed would be mistaken for the
  agent's own uncommitted work — this was reproduced directly (two tests failed with `working tree
  has 1 uncommitted change(s)` on an early version of this change that wrote the row too early) and
  is the reason `record()` cannot simply move earlier, as the dispatch itself warned.
- **A spend-write failure never costs the turn its record or the agent's delivered commit.** The
  write is wrapped; a failure folds one clause into the turn's `note` (`"... [spend row not
  recorded: <reason>]"`) and the run record, item transition, and workspace delivery all proceed
  unaffected. Priority order, by construction: workspace commit (already made, earlier, in a
  different git operation) > ledger record > spend row.
- **`SPEND_LOG`'s package-relative default is kept, not changed**, for the one caller it was always
  actually correct for: a direct import with no `Places` in play (`make test-live`'s own session
  receipt in `tests/conftest.py`). Every caller that runs a real turn now passes an explicit
  `log_path` instead of relying on it. Argued in full in `design.md`.
- **`openspec/specs/turn-cycle/spec.md`**: one ADDED requirement stating that a turn's spend row, if
  any, is committed in the same commit as its run record.
- **`decisions/0011-spend-row-committed-by-the-turn-not-the-executor.md`**: the ADR this sequencing
  decision owes per `openspec/config.yaml`'s archive guidance.

## Non-goals, stated rather than silently dropped

- **Fixing the container uid-1000-cannot-write-`/app` permission problem.** Real (ADR-0007's own
  `chown` never reaches `/app`), and this change's `spend_log_for` sidesteps it for the loop's own
  spend-ceiling reads and for every row a real turn writes — but the workflow-level bind-mount
  workaround CI currently carries is a deployment/CI concern, not something `turn.py` can fix by
  itself, and no promotion asked for it. Left as a finding, not a task here.
- **A retry or an escalation path for a spend-write failure.** The priority ordering this change
  establishes (workspace > ledger > spend) is satisfied by *not losing the rest of the turn*; making
  the platform notice and act on a missing spend row is a different, larger mechanism (a sweep over
  `ledger/runs/` cross-referenced against `ledger/spend.jsonl`) that nothing here needs to build.
- **Changing `Usage`/`RunResult`'s shape.** `total_cost_usd` already exists and is already carried
  by every executor's result; this change only changes who reads it and when.
