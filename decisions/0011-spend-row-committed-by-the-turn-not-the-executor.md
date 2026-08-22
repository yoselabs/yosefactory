# ADR-0011 — The spend row is written and committed by `turn.py::_finish`, not by the executor

**Status:** Accepted
**Date:** 2026-08-22
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** `Places` grows a shape where `places.queue` and `places.workspace` can each
point at more than one repository, or where `places.ledger.parent` (`spend_log_for`'s own
resolution) stops being a directory `commit()` can reach — at that point this decision's "write
inside `places.queue`, commit alongside the run record" needs re-examination against whatever that
new topology requires. Also revisit if a second executor is ever wired in that does not report
`RunResult.usage.total_cost_usd` faithfully — `_finish` reads it uncritically today, on the
strength of `Usage`'s existing contract.

## Context

Found live: yoselabs/factory-state Actions run 32571722314 (2026-08-22). Three jobs green, the
ledger's run record committed and pushed, and `ledger/spend.jsonl` did not exist in the repository
afterwards — the only surviving record of the run's $0.2583899 cost was a CI log with 90-day
retention.

Confirmed against disk before designing (Article XII, per `proposal.md`'s own "Why"): two
independent defects, not one. `executor/claude.py::run()` called `runtime.spend.record()` with no
`log_path` override, so it wrote to `runtime.spend.SPEND_LOG` — resolved via `paths.repo_root()`
from `spend.py`'s own `__file__`, i.e. wherever the package happens to be *installed*.
`runtime/turn.py::commit()` (the sole trailer-composing function, ADR-0004) only ever commits
explicit pathspecs inside `places.queue` — the repository a turn is actually pointed at. Under
`run-the-loop-inside-the-container`'s own topology, these are two different directories (`/app` vs.
a bind-mounted `/data/workspace`), so no pathspec against one could ever name a file living in the
other. Even had the row landed in the right repository, nothing named its path in `commit()`'s
pathspec list at all — a second, independent way for the same row to go uncommitted.

## Decision

1. **Recording moves from the executor to the turn.** `executor/claude.py::run()` no longer calls
   `spend.record()`. `runtime/turn.py::_dispose` threads `result.usage.total_cost_usd` into every
   `_finish(...)` call (the `failed`, `blocked`, planning, and normal-return paths alike), and
   `_finish` — the one function that already writes the run record and calls `commit()` — writes
   the spend row and folds its path into that same `commit()` call. This applies uniformly to every
   `Executor`, not only the real one, so the existing `FakeExecutor`-based integration suite
   exercises the commit-time guarantee without any change to the fixture itself.

2. **The spend log path is resolved from `Places`, not from the package's own install location.**
   `turn.spend_log_for(places) -> Path` returns `places.ledger.parent / "spend.jsonl"` — a sibling
   of `ledger/runs/`, inside `places.queue`. `runtime.spend.SPEND_LOG` (the module's own
   `repo_root()`-derived default) is kept, unchanged, as the default for a caller with no `Places`
   in play — `tests/conftest.py`'s `make test-live` session receipt is the one remaining real
   caller for which "the platform's own checkout" and "the repository being worked" are the same
   directory by construction. Every caller that runs a real turn (`turn._finish`,
   `loop.run_loop`'s own spend-ceiling check) now passes `spend_log_for(places)` explicitly instead
   of relying on the default.

3. **Ordering inside `_finish` is load-bearing, not incidental.** `_finish` computes the turn's
   `dirty` flag (`tree_is_dirty(places.workspace, ...)`) *before* writing the spend row, and every
   call into `_finish` happens strictly after any gate the turn's event required (`verify.
   may_write_done`'s `tree_clean` check, for a `done` proposal, demands zero uncommitted changes in
   `places.workspace` before it can pass). Under `Places.local` — today's only configuration, and
   every test fixture — `places.queue` and `places.workspace` are the same directory, so a spend
   write positioned before either check would be indistinguishable from the agent's own
   uncommitted work. This was not a theoretical risk: an earlier version of this change wrote the
   row at the top of `_dispose`, before the gate ran, and two tests failed immediately with
   `working tree has 1 uncommitted change(s)` — the write itself was the dirt the gate detected.

4. **A spend-write failure never costs the turn its run record or the agent's delivered commit.**
   The write in `_finish` is wrapped in `try/except OSError`; on failure, one clause is folded into
   the turn's `note` (`"... [spend row not recorded: <reason>]"`) and every other write proceeds.
   Priority order, by construction: the workspace commit (`_deliver_workspace`, already made,
   earlier, as a separate git operation) outranks the ledger record, which outranks the spend row.

## Consequences

- Every turn that ran an executor now commits its spend row (present or absent by `zero cost is
  real`, never silently missing) in the same `commit()` call as its run record — proven by
  `tests/runtime/test_turn_cycle.py::test_a_turns_spend_row_is_committed_not_merely_written`, which
  reads the row back out of `git show HEAD`, not `Path.exists()`.
- The CI workflow's own workaround (a separate step that commits `ledger/spend.jsonl` after the
  fact) becomes a no-op once this lands: the row is already committed by the turn itself. Removing
  that workflow step is left to whoever owns `.github/workflows/` — out of scope for a change
  confined to `src/` and its specs.
- `executor/claude.py` no longer imports or calls `runtime.spend` at all — cost recording is now a
  property of `turn.py` alone, which is also the only module `openspec/specs/turn-cycle/spec.md`'s
  new requirement (`commit-the-spend-row-inside-the-turn`) governs.
- The uid-1000-cannot-write-`/app` container permission problem (ADR-0007's `chown` never reaches
  `/app`) is **not** fixed by this decision, though it is sidestepped for every path this change
  touches: `places.queue` is never `/app` under the container's own topology, so a spend row now
  lands wherever the run record already has to land for a turn to complete at all. The permission
  defect itself is unaddressed and is not this decision's to close.

## References

- `src/yosefactory/runtime/turn.py` — `spend_log_for`, `_dispose`, `_finish`.
- `src/yosefactory/runtime/loop.py` — `run_loop`'s `spend_log` resolution.
- `src/yosefactory/runtime/spend.py` — module docstring, `SPEND_LOG`'s retained scope.
- `src/yosefactory/executor/claude.py` — `run()`, spend recording removed.
- `openspec/changes/commit-the-spend-row-inside-the-turn/design.md` — full sequencing argument and
  failure-path analysis.
- `openspec/specs/turn-cycle/spec.md` — "A turn's spend row is committed in the same commit as its
  run record."
- yoselabs/factory-state Actions run 32571722314 (2026-08-22) — the CI receipt this decision closes.
- ADR-0004 (`turn.commit()` is the sole trailer composer), ADR-0007 (container uid 1000).
