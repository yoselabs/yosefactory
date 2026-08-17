## 1. Read and re-acquire, verify before building

- [x] 1.1 architecture.md §7/§11, orchestration.md, `_night-run-2026-08-16.md` §M8/§M9/§M10, S987,
      S988, S194, S195, `src/yosefactory/board/`, `runtime/turn.py`, `runtime/loop.py` — read in
      full
- [x] 1.2 Verified `ingest()` never commits (design.md, "Found while building") before assuming
      wiring was a pure composition task

## 2. Fix `ingest()`'s missing commit

- [x] 2.1 `board/inbox.py` — appliers return `(detail, touched_path)`; `ingest()` commits
      `[touched_path, consumed_log]` per event via `runtime.turn.commit()`, one `run_id` per
      `ingest()` call
- [x] 2.2 `tests/board/test_inbox.py` — `git init` fixture (reused shape from
      `tests/runtime/test_loop.py`), assert commits landed, not just file content

## 3. `BoardConfig` and wiring into `run_loop`

- [x] 3.1 `runtime/loop.py` — `BoardConfig` dataclass (`adapter`, `actor`, `poll_seconds`),
      constructor validation
- [x] 3.2 Board poll wired into `_await_wake`'s existing loop, own cadence, ingestion only —
      no direct call to `take_turn` from the poll
- [x] 3.3 `project_all()` called once before the first turn and once after every turn
- [x] 3.4 CLI: `--board-repo`, `--board-poll-seconds`, `--board-actor` on `main()` /
      `scheduled_main()`

## 4. Tests for the S987 defense and the cadence split

- [x] 4.1 A board command applied mid-loop never calls the executor directly (a `NeverCalled`-style
      executor plus a board command present, asserted no invocation until an actual wake fires)
- [x] 4.2 Board polling happens at `BoardConfig.poll_seconds`, independent of a smaller
      `WakeConfig.poll_seconds`
- [x] 4.3 A completed turn's outcome is reflected on the (fake) board via `project_all()`
- [x] 4.4 The board is projected once before the first turn, from pre-existing queue state

## 5. The circuit receipt (Article XVI)

- [x] 5.1 Seed one real, currently-unowned debt into this repo's own `backlog/items/` — the
      `__file__`-derived path in `VOCABULARY_SPEC` / `spend.py`'s `SPEND_LOG`
- [x] 5.2 `project_all()` against `yoselabs/yosefactory` — real Issue created, quoted
- [x] 5.3 A `/`-command comment posted on that Issue (real GitHub API call)
- [x] 5.4 `ingest()` run for real — comment applied, committed, quoted from `git log`
- [x] 5.5 `run_loop` run for real, against this repository, board wired in, `max_iterations`
      bounded — outcome quoted from `ledger/runs/` and the queue's `git log`, not from the
      function's return value
- [x] 5.6 Result confirmed projected back to the same Issue via the GitHub API
- [x] 5.7 Any leg that cannot be closed: state exactly which and why, rather than a receipt about
      the wrong subject

## 6. Close

- [x] 6.1 `openspec validate wire-the-board-into-the-turn-cycle --strict`
- [x] 6.2 `make check` — confirm still $0, `ledger/spend.jsonl` unchanged by `make check` itself
      (the receipt in §5 is deliberate, separate spend, reported actual against the $5 allowance)
- [x] 6.3 Commit: change directory + `src/yosefactory/board/inbox.py` + `runtime/loop.py` +
      `tests/board/test_inbox.py` + `tests/runtime/test_loop.py` — explicit literal pathspecs,
      `-F <message-file>`, `PREK_ALLOW_NO_CONFIG=1`, `git diff --cached` confirmed empty after
- [x] 6.4 Archive; `openspec validate --specs --strict`
- [x] 6.5 Report to director: commits, `make check` $0 proof, the circuit receipt quoted leg by
      leg from disk/API, the Issue number, actual spend, anything contradicting the dispatch
