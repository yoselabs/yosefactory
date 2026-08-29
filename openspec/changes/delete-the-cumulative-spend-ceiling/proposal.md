## Why

K [[D034]] ("central control plane, local state, and the event is the wake not the assignment"),
§"Money: local, per-run, no global view", Denis's ruling verbatim: *"no global one, it is enough to
know how much we spend per issue and per run — we will use it inside the code to limit it, so I'm
not seeing a reason to have global ledger for all repos in a single one."*

Two independent reasons this is a deletion, not a repair:

1. **It has never been read.** `loop.run_loop`'s `spent_so_far()` closure calls
   `spend.total_since(start_moment, ...)` — the sum of ledger rows timestamped at or after the
   moment this loop process started. The scheduled entrypoint (`scheduled_main`, the only caller an
   unattended run ever takes) always runs `--max-iterations 1`. The ceiling check fires once, before
   that single turn has run, so the window it sums is always empty — no prior row in this process
   can exist yet. It has never once bound anything in CI.
2. **The design it reaches for is now explicitly unwanted.** Fixing the window (e.g. widening it to
   "since the scheduler last ran") would build exactly the cross-run cumulative cap D034 rules out.
   Repairing a dead check into a live one here means building the thing Denis just said not to
   build.

## What Changes

- **Delete** `LoopBound.spend_ceiling_usd`, `StopReason.SPEND_CEILING`, the `spent_so_far()` closure
  and the mid-loop cumulative-ceiling check (including the per-turn `cost_ceiling_usd` derivation
  that only existed to make that ceiling safe — S244), and the `--spend-ceiling-usd` CLI flag on
  `runtime.loop.main`.
- **Keep** `spend.record` and the per-run row it appends (D034's explicit "per-run" retention —
  unchanged, untouched).
- **Keep** `spend.total_since`, contra the dispatch that opened this change — see Design for why:
  it has a second, independent caller (`tests/conftest.py`'s live-spend session report) that has
  nothing to do with the cumulative ceiling, and the `claude-executor/spend-ledger` spec already
  documents it as the retained default reader for exactly that shape of caller.
- **Keep** `--cost-ceiling-usd` (the per-turn ceiling, `Guardrails.cost_ceiling_usd`) — this is
  D034's actual enforcement point and is untouched by this change.
- **Keep** `LoopBound.max_iterations` mandatory — ADR-0003 is not disturbed.
- **Keep** `scheduled_main` — see Design for why it survives losing the flag that used to be most of
  its stated reason to exist.

## Breaking change

`~/Workspaces/factory-state`'s `take-a-turn.yml` passes `--spend-ceiling-usd` today. After this
change that invocation dies at argparse (`unrecognized arguments`). This is deliberate, not
softened: cron is off, there are no live runs, and a flag that parses but silently does nothing is
worse than one that is gone. **`factory-state` is not touched by this change** (different repo,
different owner) — its `take-a-turn.yml` must stop passing `--spend-ceiling-usd` before its next
run.

## Impact

- Affected specs: `turn-loop/wake-and-bound` (MODIFIED — the bound requirement drops its
  spend-ceiling half).
- Affected code: `src/yosefactory/runtime/loop.py` (LoopBound, StopReason, run_loop, main, the CLI
  parser); `tests/runtime/test_loop.py` (spend-ceiling test block deleted/rewritten); no change to
  `src/yosefactory/runtime/spend.py`, `src/yosefactory/runtime/config.py`,
  `src/yosefactory/executor/claude.py`, or `tests/conftest.py`.
