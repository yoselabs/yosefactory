## 1. Read and re-acquire

- [x] 1.1 `orchestration.md`, `architecture.md` §6/§11, `S195`, `runtime/turn.py::take_turn`,
      `Places` — read in full before designing anything
- [x] 1.2 Confirmed no existing caller drives `take_turn` more than once (`grep -rl take_turn src/`
      → only `runtime/turn.py` itself); confirmed no CLI, no scheduler, no `.github/workflows/`
      exist yet in this repo

## 2. The loop

- [x] 2.1 `src/yosefactory/runtime/loop.py`: `LoopBound`, `WakeConfig`, `WakeReason`, `StopReason`,
      `LoopStep`, `LoopReport`
- [x] 2.2 `_queue_head`, `_await_wake` — the three wake conditions, cheapest-first, polling via
      injectable `sleep_fn`/`now_fn`
- [x] 2.3 `run_loop()` — self-chains `take_turn`; bound checked before the wait (iteration count)
      and again after it (spend), per design.md D3
- [x] 2.4 `main()` — CLI entry point, `Places.local` only, real `claude.run()` executor under
      `IsolationPolicy(isolated=True)`

## 3. Tests — every receipt in this file costs $0

- [x] 3.1 `LoopBound`/`WakeConfig` validation (mandatory `max_iterations`, positive
      `spend_ceiling_usd`, positive intervals)
- [x] 3.2 Self-chaining at $0: a quiescent backlog (one `snoozed` item) produces N real
      `nothing-ready` ledger rows across N self-chained turns, verified by reading
      `ledger/runs/*.json` from disk (Article XII) and the queue's own git log
- [x] 3.3 Startup fires immediately, no wait, regardless of heartbeat length
- [x] 3.4 Each wake condition isolated: ready item, external event (queue `HEAD` moves), heartbeat
- [x] 3.5 Spend ceiling: recorded spend crossing the ceiling **during** a wait stops the next turn
      before it starts, against an isolated `spend_log` fixture (never this checkout's own
      `ledger/spend.jsonl`)
- [x] 3.6 Spend ceiling ignored when unset; `max_iterations` alone still bounds the loop
- [x] 3.7 `make check`: 285 passed / 11 deselected (272 baseline + 13 new), zero live spend
      (`ledger/spend.jsonl` unchanged by `make check` — confirmed by `git status --porcelain`)
- [x] 3.8 **Added after director review (S194-shaped finding): the wake reason was not durable.**
      `LoopReport.steps` lived only in memory; a fresh reader of the repo could not tell *why* a
      turn ran. Added `_record_wake` (a committed `<slug>.wake.json` sidecar, joined by `run_id`)
      and three tests asserting it exists on disk, is git-committed, and matches the in-memory
      report — not merely that the report claims a reason.

## 4. The end-to-end receipt (Article XVI)

- [x] 4.1 Ran `pytest -q tests/runtime/test_loop.py` directly (not only via `make check`) and read
      the produced `ledger/runs/*.json` files from disk in the test's own tmp queue, confirming
      three real records, three real commits, `outcome: nothing-ready` on each
- [x] 4.2 **Corrected per director review before running:** `max_iterations=1` would only receipt
      `take_turn`, already covered by the a2web `45092c4` / `$0.0447` canary. Ran instead with
      **two items already `ready` in the queue and `max_iterations=2`**, against a real,
      separate queue+workspace pair (mirroring `test_turn_integration.py`'s own fixture shape,
      never this checkout as workspace) — script at
      `/private/tmp/.../scratchpad/live_loop_receipt.py` (not committed). Result: two turns, two
      **distinct** `run_id`s (`turn-...67ccad11`, `turn-...d0a72fc5`), second turn's wake reason
      **`ready_item`** — read from the durable `.wake.json` sidecar, not inferred — proving the
      loop chained on its own with no human between the two `take_turn` calls. Both `advanced`.
      Stopped by `max_iterations`. Spend: $0.284952 + $0.287857 = **$0.572809**, both rows
      appended to this repo's real `ledger/spend.jsonl` (not the throwaway queue's).

## 5. Close

- [x] 5.1 `openspec validate add-turn-loop --strict` passed
- [x] 5.2 Committed `88eecd4`: change directory, `src/yosefactory/runtime/loop.py`,
      `tests/runtime/test_loop.py`, `ledger/spend.jsonl` (the two live rows from 4.2) — explicit
      literal pathspecs, `-F <message-file>`, `PREK_ALLOW_NO_CONFIG=1`, `git diff --cached`
      confirmed empty after
- [ ] 5.3 Archived; `turn-loop/wake-and-bound` promoted; `openspec validate --specs --strict`
      passes afterward
- [ ] 5.4 Reported to the director: commits, `make check` result, the live receipt's exact command
      and ledger/spend rows, the loop's bound in one sentence, anything found that contradicts the
      dispatch
