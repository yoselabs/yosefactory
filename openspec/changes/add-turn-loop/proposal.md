# add-turn-loop

Promotion: architecture.md's own naming — *"there is no workflow object... For the code itself,
there are no workflows, there's only functions"* (S173) — draws the line this change closes on the
other side of. `take_turn` is that function. Nothing before this change drove it more than once
without a person retyping the call. **A factory is `take_turn` driven by something that is not a
person**, and until now the something was always a terminal.

## Why

S195 found nine mechanisms declared and never reached, and named the pattern precisely: *"a typed
field with no writer is not a smaller version of a typed field."* The same shape was sitting one
level up and unnoticed — `take_turn` itself had no caller but a human or a single test invocation.
Every "live" receipt in `tests/runtime/test_turn_integration.py` calls it exactly once and stops.
That is not sloppiness; it is the state a program is in before the loop exists, which is what this
change builds.

**The instruction this change was dispatched against named `GitHub Actions` /
`repository_dispatch` as the mechanism, and that is treated here as a deployment target, not the
deliverable (Article XVI).** A `.github/workflows/*.yml` that has never fired is exactly what S195
found nine of already, and this repo has eleven archived changes with a wiring receipt and zero with
an end-to-end one (orchestration.md, Article XVI). So the loop this change builds is runnable and
observable **on this machine**, with its own real ledger rows as the receipt, and a CI adapter is
explicitly out of scope — a thin wrapper the design makes possible, not something this change ships.

**Money is real once this lands.** A loop that self-chains is the first thing in this program
capable of spending without a human between iterations. The bound is therefore not an afterthought:
`LoopBound` is mandatory on every call to `run_loop` and has no infinite mode.

## What Changes

- **New capability** `turn-loop/wake-and-bound`: `runtime/loop.py`'s `run_loop()` self-chains
  `runtime.turn.take_turn` in-process, waking on whichever of three conditions fires first —
  a ready item, the queue's own HEAD moving (an external event), or a heartbeat interval — and
  stopping the first time either half of its bound holds: `max_iterations` turns run, or (when set)
  cumulative spend recorded in `ledger/spend.jsonl` since the loop started reaches
  `spend_ceiling_usd`.
- **The wake reason is durable, not only returned.** Each turn's wake condition is written to a
  committed `<slug>.wake.json` sidecar in `ledger/runs/`, joinable by `run_id` to that turn's own
  record — added after an S194-shaped review finding: `LoopReport.steps` alone would have made
  *why a turn ran* readable only from the in-memory return value, unreachable from disk exactly
  like the nine instances S195 catalogued.
- **A CLI entry point**, `python -m yosefactory.runtime.loop`, so the loop is invocable on this
  machine without writing a script first — matching `runtime/stall.py`'s own `main()` pattern.
- **No change to `take_turn` itself.** Every iteration is a complete, independent call exactly as a
  human's was; the loop owns only *when* to call it again and *when* to stop.

## Capabilities

### New Capabilities

- `turn-loop/wake-and-bound`: drives `take_turn` repeatedly from three wake conditions
  (ready item, external event, heartbeat) under a mandatory bound (iteration count, and optionally
  a spend ceiling read from the real spend ledger), self-chaining after every turn until the bound
  stops it, and durably recording which wake condition produced each turn.

### Modified Capabilities

None. `take_turn`, `Places`, and every existing capability are unchanged; this change adds a caller.

## Impact

- `src/yosefactory/runtime/loop.py` — new module: `LoopBound`, `WakeConfig`, `WakeReason`,
  `StopReason`, `LoopStep`, `LoopReport`, `run_loop()`, `main()`.
- `tests/runtime/test_loop.py` — new: bound validation, self-chaining at $0 (the `nothing-ready`
  path never starts an executor), each wake condition isolated, the spend ceiling honoured against
  an isolated ledger.
- No changes to `runtime/turn.py`, `runtime/config.py`, `runtime/spend.py`, or any `openspec/specs/`
  capability other than the one this change adds.

## Non-goals

- **A GitHub Actions / `repository_dispatch` adapter.** Named in the original sketch as the
  deployment target; not built here, and not needed for the receipt this change is scored on
  (Article XVI — the loop's own ledger rows, produced by a real execution on this machine).
- **Cross-repo / cross-machine loop operation.** `run_loop`'s CLI runs `Places.local` only; a
  caller that imports `run_loop` directly can already pass a cross-repo `Places`, but wiring that
  into the CLI is a separate, larger change (guardrails around `cas_push`/`cross_machine` in
  `take_turn` itself are still the open item architecture.md §4 names).
- **A sweeper turn or duplicate detection.** architecture.md §5 names the sweeper as a separate,
  deliberate exception to one-item-per-turn; this loop calls `take_turn` unmodified and does not
  add a sweeper turn type.
- **Changing `Guardrails.cost_ceiling_usd`.** That is a per-turn cap enforced inside one executor
  invocation; `LoopBound.spend_ceiling_usd` is a cross-turn cap read from the durable ledger after
  the fact. Both are real and neither substitutes for the other.

## The receipt question (Article XVI)

**What would distinguish built from works:** run the loop for real against this repository's own
queue and read `ledger/runs/*.json` afterward — if the loop is broken, either fewer records exist
than iterations requested, or the loop never returns (no bound), or a wake condition never fires and
the loop hangs on an idle backlog forever. The receipt is `ledger/runs/`'s own row count and
`outcome` fields, checked from disk, not from `LoopReport`'s in-memory return value (Article XII).
