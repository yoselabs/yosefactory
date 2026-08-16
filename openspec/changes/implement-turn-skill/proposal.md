## Why

Every part of this platform built so far is a part: the item format folds, the question frame closes,
the guardrails bound and detect. Nothing runs a turn. The unit the whole design rests on — read
state, do exactly one thing, record it, commit, exit — has no implementation, so no ledger row has
ever been produced by the machine rather than by hand.

The dispatch named no single promotion id. The design entities it acts on are `S079` (the two-phase
turn is the unit), `S173` (*"for the code itself, there are no workflows, there's only functions"*),
`architecture.md` §1 (the LLM proposes, deterministic code disposes), `architecture.md` §4 (the claim
is a commit, not a lease), `D019` (the frame is the payload), and `S098`/`S171` (prompt adherence is
the measured-unreliable mechanism, so invariants may not live in a prompt).

## What Changes

- **New `src/yosefactory/runtime/turn.py`** — one turn as a function of repository state: acquire,
  classify, do one item, record, commit, exit. No workflow object, no stage list, no pipeline.
  Sequencing is a consequence of item state.
- **New skill file** — the prompt the agent runs during step 3. Held to ~100 words: where to write,
  what shape, one event only. The invariants are *not* restated there; they are enforced by the fold.
- **Steps 1–2 become a deterministic pre-check.** A turn with nothing ready spawns no agent process
  and exits at $0, having written a `nothing-ready` turn record.
- **`turn.py` is the sole writer of the `TurnRecord`.** `RunResult.outcome` (the executor seam) is a
  process fact — did the agent run and produce a verdict. `TurnRecord.outcome` is a protocol fact —
  did the turn advance. Two writers would put two different questions in one slot. Arbitrated by the
  director 2026-08-16; the matching change to `runtime/supervise.govern` is YF-4's, not this one.
- **The agent proposes exactly one typed event**, written as JSON to a path the script supplies. The
  script validates by appending it to the item's log and re-folding through `protocol.backlog.ITEM`.
  An illegal transition, an unknown event or a missing field fails the read, and the event does not
  survive the turn.
- **`done` passes `verify.may_write_done`** before the event is written. There is no path from a
  self-report to a `done` item.
- **Claiming is a commit**, taken before any agent runs, and the turn holds `supervise.single_flight`
  for its whole duration.
- **First rows in `ledger/runs/`.** The directory does not exist yet; the first turn creates it.

## Capabilities

### New Capabilities
- `turn-cycle`: what one turn is — the five steps, what decides plan-versus-act, what the agent is
  allowed to propose, what the script checks before writing, and what a turn commits.

### Modified Capabilities
<!-- None. `backlog-item-format`, `question-frame` and `run-guardrails` are consumed exactly as
     specified; this change adds no requirement to any of them. The one requirement that must change
     — govern not writing the turn record — belongs to a concurrent change owned by another worker. -->

## Non-goals

- **The steering inbox.** `design-e2e.md` §1 makes "read the steering inbox" step 1 of every turn.
  No inbox format exists anywhere in this repository and this change does not invent one. Step 1
  reads `questions/` for answers that unblock items — that format is specified and on disk — and the
  inbox is recorded here as an unimplemented gap belonging to the board-adapter work (M2, unscheduled).
- **The CAS claim push.** `architecture.md` §4 resolves cross-machine collisions with
  `git push --force-with-lease=<ref>:<sha>`. This change puts the claim in a local commit and leaves
  the push behind a config flag that is off by default. The distinction that matters, and that the
  spec states: single-machine concurrency is safe today because the turn holds `single_flight`;
  **multi-machine** concurrency is not, and enabling it must fail loudly rather than silently.
- **Multi-item turns.** A sweeper turn touching N items is a documented exception in
  `architecture.md` §5 and is not built here.
- **Zombie reclamation.** A lease TTL that returns a dead worker's claim to `ready` is a liveness
  concern, not a correctness one, and waits for evidence that a worker has actually died.
- **Any change to `protocol/`, `runtime/supervise.py`, or the executor.** Consumed as they are.
- **Scheduling.** Nothing here fires on a clock. A turn is invoked; it does not invoke itself.

## Impact

- **New**: `src/yosefactory/runtime/turn.py`, the skill file, `tests/runtime/test_turn_cycle.py`,
  `ledger/runs/` (created at first run), `backlog/items/*.jsonl` (written by the first planning turn).
- **Consumed unchanged**: `protocol/eventlog.py`, `protocol/backlog.py`, `protocol/turn.py`,
  `runtime/runs.py`, `runtime/verify.py`, `runtime/supervise.py`, `runtime/config.py`.
- **Depends on**: the executor seam `run(frame, workspace, limits) -> RunResult`, owned by another
  worker and not yet on disk. This change ships against an injected executor — a fake in tests, the
  real one when it lands. The live two-turn acceptance run is sequenced by the director, not here.
- **Acceptance**: one turn reads an empty backlog, plans one item, records, commits, exits; a second
  turn picks up where the first stopped with nothing passed between them except the repository.
