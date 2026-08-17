# Design — add-turn-loop

Motivation: see [proposal.md](proposal.md) — Why. Requirements: see
`specs/turn-loop/wake-and-bound/spec.md`.

## Context

`runtime/turn.py::take_turn` is a complete, self-contained transaction: acquire, classify, do one
item, record, commit, exit. Nothing in the repository calls it twice from inside one process.
S195's own diagnosis of the platform generalises one level up here: `take_turn` is a typed function
with no caller but a human retyping the call or a test that stops after one invocation.

Money changes the shape of the problem the moment a caller exists that does not stop on its own.
Every executor this program can drive (architecture.md §7b) has neither a cost ceiling nor a wall
clock of its own — both are the harness's, permanently. A loop is the harness, so the bound is not
optional polish; it is the property that makes "the loop ran overnight" not read as an incident.

## Goals / Non-Goals

**Goals:**
- Self-chaining: after a turn's record is written, decide whether to run another without a human
  re-invoking anything.
- Three wake conditions, argued rather than assumed from the dispatch's starting list.
- A bound stated in one sentence, mandatory, checked so that spend accrued *during* an idle wait is
  still caught before the next turn starts.
- Runnable and observable on this machine — a real process, a real git-committed ledger.

**Non-goals:**
- No GitHub Actions / `repository_dispatch` adapter (proposal.md — Non-goals).
- No change to `take_turn`, `Places`, or any existing capability.
- No cross-repo or cross-machine CLI wiring — `run_loop` accepts any `Places`, but `main()` builds
  only `Places.local`.
- No new persistence format. Wake conditions read `runtime.turn.items()`/`eligible()` and a plain
  `git rev-parse HEAD`; the bound reads the existing `runtime.spend` ledger. Nothing new is written
  to disk beyond what `take_turn` already writes per turn.

## Decisions

### D1 — In-process `while` loop, not `repository_dispatch`

**Chosen:** `run_loop()` is a Python function holding a `while True` that calls `take_turn` and
re-evaluates. `main()` runs it under `python -m yosefactory.runtime.loop`.

**Over:** the dispatch's own suggestion — a GitHub Actions workflow that re-triggers itself via
`repository_dispatch` after each run.

**Why:** Article XVI, argued in the proposal. A workflow file that has never fired is indistinguishable
from a workflow file that works, until the day it is needed — this repo already holds eleven
archived changes with exactly that shape of unverified receipt (S195). An in-process loop can be run
right now, on this machine, and its ledger rows read afterward. A CI adapter remains buildable later
as a thin wrapper calling `main()` once per dispatch; it inherits this design rather than replacing
it.

### D2 — Three wake conditions, checked cheapest-first, blocking on none of them being free

**Chosen:** `_await_wake` polls, in order: (1) does `items(queue)` contain an `eligible()` item —
free, no git call; (2) has `git rev-parse HEAD` moved since the last check — one subprocess; (3) has
`heartbeat_seconds` elapsed since the last turn — a clock read. It sleeps `poll_seconds` between
checks.

**Over:** a single condition (e.g. heartbeat-only polling), or a push/webhook mechanism.

**Why a poll, not a push:** architecture.md §6 states it directly for the board — *"git has no
change notification, so the loop will poll"* — and Argo CD, cited there as the largest git-as-desired-
state deployment, polls every three minutes by default rather than building a push path. This
program has no server to receive a webhook against; a poll is the honest mechanism available.

**Why three, not one:** the dispatch's starting list separated *work exists* from *something
landed* from *time elapsed*, and each answers a different question a single condition cannot:
a ready item answers "is there work"; the queue's HEAD moving answers "did something external
happen that a ready-item check alone would miss" — e.g. an answer landing that unblocks an item
without itself becoming instantly `ready` inside the same poll window, or any other queue mutation a
future writer adds; the heartbeat answers "should we check for planning work even though nothing
signalled." Dropping the heartbeat would mean a backlog that is fully quiescent (`should_plan`
would return `True` but nothing ever asks) never gets a planning turn — the exact green stall
architecture.md §8 names as this platform's actual failure mode, just relocated from "no
`advanced` in the window" to "no turn at all."

**Why the first turn is unconditional (`WakeReason.STARTUP`):** a loop that waited out its own
heartbeat before checking the backlog it was just handed to run against would be strictly worse than
calling `take_turn` once by hand and then starting the loop — the mechanism this change replaces.

### D3 — The bound: `max_iterations` mandatory, `spend_ceiling_usd` optional, checked twice per
iteration in different places

**Chosen:** `LoopBound.max_iterations` has no default and `__post_init__` refuses anything but a
positive int. `spend_ceiling_usd` is optional. The iteration check runs *before* the wake-wait (a
count already at its cap needs no wait to know that); the spend check runs *after* waking, right
before `take_turn` is called (spend accrued *during* the wait — by this loop's own last turn landing
in the ledger, or by another process entirely — must still stop the next turn before it starts).

**Over:** a single check at the top of the loop, before waking.

**Why the split matters and is not stylistic:** a spend check made only before the wait can be
satisfied at the moment it runs and then falsified during a long heartbeat wait, letting one more
turn fire after the ceiling was already crossed. Moving the spend check to after the wait closes
that window. `tests/runtime/test_loop.py::test_the_loop_stops_at_the_spend_ceiling_before_the_iteration_bound`
is the regression receipt: it records a spend row mid-sleep and asserts the loop stops *before* a
second turn runs, not after one more.

**Why `spend_ceiling_usd` reads `ledger/spend.jsonl` rather than trusting the executor's own
`RunResult.usage`:** `ledger/spend.jsonl` is the durable, cross-invocation record
(`record-live-spend-and-gate-make-check`); an in-memory running total inside `run_loop` would not
survive a crash and would double as a second source of truth the ledger could silently disagree
with. Reading the ledger keeps `run_loop` a reader of the same fact everything else reads (Article
XII's discipline applied to the loop's own bound).

**Why no default spend ceiling:** a loop with no money-spending turn ever eligible (a backlog held
entirely in `snoozed`/`blocked` states, say) has nothing for a spend ceiling to bound, and forcing
every caller to name one would either be an arbitrary number or `None` spelled differently.
`max_iterations` alone is always sufficient to stop the loop; `spend_ceiling_usd` is additional
insurance for the case where a turn can spend.

### D4 — `main()` builds `Places.local` only, and constructs the real `claude` executor directly

**Chosen:** the CLI wraps `executor.claude.run()` under `IsolationPolicy(isolated=True)` (the
executor's default, safe posture — `test_turn_integration.py`'s own module docstring notes that
posture denies tool calls headlessly, which is the point for an unattended default) against
`Places.local(repo)`.

**Over:** a CLI that takes an executor name/vendor flag, or that builds a cross-repo `Places`.

**Why:** matching `runtime/stall.py::main`'s own scope discipline — one clear default path,
callable today, rather than a general launcher this change was not asked to build. A caller that
needs cross-repo operation or a non-default executor already has the tool: `run_loop` itself,
importable directly with any `Places` and any `Executor`.

### D5 — The wake reason is committed to the queue as a sidecar, not folded into `TurnRecord`

**Chosen:** after `take_turn` returns, `run_loop` writes `<slug>.wake.json` (`{"run_id", "wake"}`)
next to that turn's own ledger record and commits it via `turn.commit()`, reusing the returned
`run_id` for the commit trailer.

**Over:** widening `TurnRecord`'s frozen shape with a `wake` field; or leaving the wake reason only
in `LoopReport`, in memory.

**Why this was added, not designed in from the start:** review caught it as an S194-shaped gap —
`LoopReport.steps` is the only place `WakeReason` lived, and a report that only the calling process
holds is unreachable the moment that process exits or a caller logs a summary instead of the object.
That is the same shape as every S195 instance: declared, unreachable. The fix could not be "add a
field to `TurnRecord`" — that record is frozen because every row is compared against every other
row (`protocol/turn.py`'s own module docstring), and `take_turn` already commits it before `run_loop`
ever sees the result, so there is no seam to inject a caller-supplied field without changing
`take_turn`'s contract, which design.md's own Non-goals rules out. A sidecar, written and committed
after the fact by the caller that has the information, keeps `take_turn` untouched and still lands
the fact on disk, committed, joinable by `run_id` — the property Article XII and S194 both ask for.

**Cost accepted:** one extra commit per turn (`turn(<run_id>): wake=<reason>`), and the sidecar can
lag behind `publish()` — `run_loop` does not re-push after writing it, so a wake record can sit
locally alongside its turn's own commit until the next `advanced` turn's `publish()` call pushes
both. Named rather than fixed: `publish()`'s per-turn push-on-`advanced`-only behaviour predates
this change (`turn-publication`) and this file does not alter it.

## Risks / Trade-offs

- **Polling has latency.** `poll_seconds` bounds how quickly the loop notices a ready item or an
  external event; a shorter interval trades CPU/subprocess overhead for responsiveness. Left as a
  caller-tunable default (5s) rather than hard-coded, matching `WakeConfig`'s own shape.
- **`_queue_head` shells out to `git rev-parse HEAD` on every idle poll.** Cheap, but not free at a
  short `poll_seconds` over a long heartbeat window. Not optimised here — no measurement yet
  motivates it, and `runtime/turn.py`'s own `_git` helper takes the identical cost per commit
  already.
- **The spend ceiling is a post-turn detector, like `Guardrails.cost_ceiling_usd`.** A turn that
  crosses the ceiling mid-run still finishes; the loop stops the *next* one. This mirrors the
  existing per-turn cost-ceiling design (`claude-executor/cost-ceiling`) rather than inventing a
  new enforcement shape, and is named here so it is not mistaken for a hard kill switch.

## Migration Plan

Additive only. No existing capability, record shape, or CLI changes. A caller not using `run_loop`
is unaffected.

## Open Questions

- Whether a caller ever needs `run_loop` itself to be interruptible mid-wait (e.g. `SIGTERM` during
  a heartbeat sleep) rather than only between iterations — not exercised by this change's receipt,
  and Python's default signal handling already interrupts a blocking `sleep_fn` call with a
  traceback, which is a legible failure rather than a silent one, so left unaddressed until a real
  deployment needs graceful shutdown.
