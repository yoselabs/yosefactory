# ADR-0020 — Delete the cumulative spend ceiling; it never fired and the design is unwanted

**Status:** Accepted
**Date:** 2026-08-29
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a caller needs `run_loop` to run more than one iteration per unattended
invocation (i.e. `scheduled_main` stops being called with `--max-iterations 1`), which would make
a cumulative check within one process meaningful again, or K reverses D034 and asks for a
cross-run/cross-repo spend view.

## Context

`add-turn-loop` (ADR-0003) gave `LoopBound` a mandatory `max_iterations` and an optional
`spend_ceiling_usd`: a cumulative dollar cap, checked between iterations, against
`spend.total_since(loop_start_moment)`. K [[D034]] (2026-08-29, "central control plane, local
state, and the event is the wake not the assignment") rules explicitly that no cross-run or
cross-repo spend view is wanted — Denis's own words: *"it is enough to know how much we spend per
issue and per run — we will use it inside the code to limit it, so I'm not seeing a reason to have
global ledger for all repos in a single one."*

Separately, and found independently of that ruling: the ceiling has never once fired. Every
unattended invocation (`scheduled_main`, the only caller a scheduler ever takes) runs
`--max-iterations 1`. The ceiling check reads `spend.total_since(this_process's_start_moment)`
before the one turn that process will ever run — the window it sums is by construction empty every
time the check executes. Fixing the window (e.g. widening it to span across processes) would build
exactly the cross-run cumulative cap D034 rules out; there is nothing left to repair toward.

## Decision

Delete:

- `LoopBound.spend_ceiling_usd` and its validation
- `StopReason.SPEND_CEILING`
- the `spent_so_far()` closure and the mid-loop cumulative-ceiling check, including the per-turn
  `cost_ceiling_usd` derivation (S244) that existed only to make that ceiling safe
- the `--spend-ceiling-usd` CLI flag on `runtime.loop.main`

Keep, unchanged:

- `spend.record` and the per-run row it appends (D034's explicit retention)
- `--cost-ceiling-usd` / `Guardrails.cost_ceiling_usd` — the actual, remaining enforcement point
- `LoopBound.max_iterations`, mandatory (ADR-0003 stands)
- `scheduled_main` — see below

Overturned from the dispatch that opened this change, on exploration (Article VII,
`orchestration.md`):

- **`spend.total_since` is kept**, not deleted. It has an independent caller —
  `tests/conftest.py::pytest_sessionfinish`'s "live spend this session" report after `make
  test-live` — that has nothing to do with the loop's cumulative ceiling. The
  `claude-executor/spend-ledger` spec already documents this function as the retained default
  reader for exactly that shape of caller (no `Places` in view). Deleting it would have broken a
  caller this change has no mandate over. What was actually dead was one caller
  (`loop.spent_so_far`), not the function.
- **`LoopReport.spend_usd` is kept**, computed inline at its one remaining call site
  (`spend.total_since(start_moment, resolved_spend_log)`) instead of through the deleted closure.
  This is D034's own "per-run" report (`main()`'s `spend: $X.XXXX` stdout line), not the ceiling.

## `scheduled_main` — kept, not collapsed into `main`

`unattended=True` (which `scheduled_main` sets) gated three things, not one: `--spend-ceiling-usd`
required (deleted here); the isolation posture (`workspace_scoped`, no human to approve a tool
prompt); and the publish-declined-by-default posture (D022 §2). Losing the first leaves the other
two — both real, load-bearing differences between a person at a terminal and an unattended
scheduler — untouched. Collapsing `scheduled_main` into `main` would mean either giving every
interactive invocation the workspace-scoped/declined-publish posture (wrong — D022 already carved
that out for the human-present case) or losing those protections for the scheduled path (worse).
`scheduled_main` survives as exactly what it already was minus one required argument.

## Breaking change

`~/Workspaces/factory-state`'s `take-a-turn.yml` passes `--spend-ceiling-usd` today. After this
change that invocation fails at argparse (`unrecognized arguments: --spend-ceiling-usd`). This is
deliberate: cron is off, there are no live runs, and a flag that parses but silently does nothing
is worse than one that is gone. **`factory-state` is not touched by this change** — it must stop
passing `--spend-ceiling-usd` before its next run.

## Consequences

- One fewer moving part between `main()`'s CLI surface and `LoopBound`; the only spend enforcement
  left in this codebase is the per-turn `--cost-ceiling-usd`, which is where D034 says enforcement
  belongs.
- Per-run and per-issue spend remain fully readable from `ledger/spend.jsonl` directly — no
  regression in observability, only in a check that never worked.
- `openspec/specs/turn-loop/wake-and-bound/spec.md`'s "The loop is bounded, and the bound is
  mandatory" requirement is removed (Article XIV: as a whole block, not shrunk via MODIFIED) and
  replaced by "The loop is bounded by iteration count", carrying only the `max_iterations` half
  forward.
