# wire-the-board-into-the-turn-cycle

Promotion: `_night-run-2026-08-16.md` §M10's own closing line — "**WIRE IT** — the board is built
and the loop does not call it. `ingest()`/`project_all()` are standalone. this is the one that
turns three shipped changes into one system." Three capabilities exist (`turn-loop`,
`containerized-loop`, `board-projection`); none calls another.

## Why

A comment typed on a phone does not reach a running loop today, and a loop's own results do not
reach the board. `add-board-projection-and-inbox` built both directions of the board and named
wiring them into `run_loop` as an explicit non-goal — "a deployment decision for the next change,
not this one." This is that change.

## What Changes

- **`run_loop` gains an optional `board: BoardConfig`.** When set, two things happen that were
  previously only reachable by a person calling `ingest()`/`project_all()` by hand:
  - **Ingestion, at its own cadence.** The loop polls the board for unconsumed commands on
    `BoardConfig.poll_seconds` — a frequency independent of `WakeConfig`'s own polling and of
    `take_turn`'s wake conditions. Applying a command is a pure git write (`ingest()` never calls
    an executor); if the write moves the queue's `HEAD`, the loop's *existing*
    `EXTERNAL_EVENT` wake condition — unmodified — is what turns that into a turn. **No new path
    reaches the executor from a board read.** This is the design constraint the dispatch named
    explicitly: board polling and executor waking stay two different frequencies, structurally,
    not by convention.
  - **Projection, after every turn.** Once a turn's record is written, `project_all()` mirrors
    the queue's current state — including the item that turn just touched — back to the board.
    Also run once before the loop's first turn, so the board reflects whatever state existed
    before the loop started.
- **`board.inbox.ingest()` now commits what it applies.** Found while wiring, not designed ahead
  of it: `ingest()` wrote item and question events to disk but never committed them — every prior
  test exercised it against a bare directory with no git repo at all. Left as-is, a board command
  applied by a running loop would sit in the working tree uncommitted, invisible to `git log`, to
  a push, and to `_refuse_if_dirty`'s guard on a *subsequent* start (though not the current run,
  since the check is only at startup). This is a real correctness gap for a wired loop, not a
  pre-existing design decision being revisited — architecture.md §7 says the reducer's whole basis
  is "git is the source of truth," and an uncommitted git write is not yet part of that truth.
- **CLI**: `python -m yosefactory.runtime.loop` (and the installed `yosefactory-loop*` scripts)
  gain `--board-repo owner/name` (optional; wires a real `GitHubIssuesAdapter`),
  `--board-poll-seconds` (default 60), `--board-actor` (default `board`).

## Non-goals

- **Forgejo**, still named as the second adapter, still not built.
- **Loop-to-loop messaging / the `GITHUB_TOKEN` echo hazard.** One operator, one loop, one board.
- **A production PAT.** Unchanged from `add-board-projection-and-inbox`: `gh`'s local session or
  `GH_TOKEN` in a container, never a credential this change requests or stores.
- **Fixing [[S987]] (the idle-wake billing cost) or [[S988]]'s general form (undocumented guard
  scopes) beyond what this change's own board-wiring inherits from them.** Both are named,
  unaddressed debts from before this change; board wiring does not make either worse (ingestion
  itself never starts an executor — see above), and does not attempt to fix either here.

## Capabilities

### New Capabilities
- `turn-loop/board-wiring`: `run_loop` ingests board commands and projects turn results, at a
  cadence decoupled from `take_turn`'s own wake conditions, with no new path from a board read to
  an executor invocation.

### Modified Capabilities
- `board-projection/inbox`: `ingest()` commits every event it applies or rejects — additive
  (nothing in the existing spec said otherwise; this names a behavior that was previously
  unspecified and, in the implementation, simply missing).

## Impact

- `src/yosefactory/board/inbox.py` — commits added; applier functions now report which path they
  touched so the commit names it.
- `src/yosefactory/runtime/loop.py` — `BoardConfig`, board polling wired into `run_loop`'s wait
  loop and turn cycle, CLI flags added to `main()`.
- `tests/board/test_inbox.py` — now runs against a real (throwaway, per-test) git repo, since
  commits are asserted; same fixture shape `tests/runtime/test_loop.py` already uses.
- `tests/runtime/test_loop.py` — new tests: board commands never invoke the executor; a command
  surfaces as a turn only through the existing `EXTERNAL_EVENT` wake; board polling cadence is
  independent of `WakeConfig.poll_seconds`; a completed turn's result reaches the board via
  `project_all()`.
- No change to `runtime/turn.py`'s `take_turn` itself — the wiring lives entirely in `loop.py`,
  matching the existing split between "one turn" and "the loop around it."

## The receipt question (Article XVI)

**What would distinguish built from works:** a real backlog item, seeded in this repo's own
`backlog/items/`, reaches a real Issue on `yoselabs/yosefactory`; a `/`-command comment posted on
that Issue is ingested and applied as a committed git event; `run_loop` — pointed at this
repository, its own board wired in — picks the item up and runs a real turn against it; the
outcome is projected back to the same Issue. Checked from the GitHub API and this repo's own
`ledger/`, not from any function's return value (S194).
