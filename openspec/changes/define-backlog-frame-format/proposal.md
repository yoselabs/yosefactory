## Why

A work item has no on-disk shape yet, so nothing else in the design can be built: the turn skill picks an item, the steering inbox amends one, and the guardrails check what one claims to have done. All three read the same thing and it does not exist.

Promotion: dispatch-plan.md change 1, dispatched 2026-08-16. Design authority: architecture.md §2 (the Item), §3 (the state graph), §4 (append-only storage as the concurrency design), §5 (blocked-until). Frame from [[D019]]; append-only from [[D002]].

The format decision is not cosmetic. architecture.md §4 argues that the storage format *is* the concurrency design — a rewritten state file conflicts between concurrent writers, an append-only log of one record per line cannot — so choosing the file shape settles how six workers and N turns share one tree, before any locking mechanism is written.

## What Changes

- **New `backlog/` directory**: one append-only log per work item, `backlog/items/<id>.jsonl`, one JSON event object per line. Nothing in it is ever rewritten or deleted.
- **Current state is the fold of the item's own trail**, never a stored field. `state`, `lease`, `awaiting`, `successor` and `survivor` are all derived by replaying events in file order.
- **Thirteen states**, per architecture.md §3: `ready · claimed · doing · blocked · falsified · failed · done · cancelled · duplicate · needs_split · snoozed · poison · abandoned`. `terminal` is a **derived predicate** over five of them, not a fourteenth state — see design.md; this is an explore-time correction to the dispatch and is flagged as such rather than applied quietly.
- **`awaiting` carries `kind · ref · who · since · return_to · nudge_at · deadline · on_timeout`** (§5). `return_to` is written at block time and never recomputed.
- **`falsified` emits a successor**, and the successor's own log records what falsified its predecessor as input ([[D019]]). The falsified item stays readable in full; nothing is rewritten to point forward.
- A worked fixture pair under `backlog/` demonstrating the falsified→successor round-trip, and the acceptance test that reads it.

## Capabilities

### New Capabilities
- `backlog-item-format`: the on-disk representation of a work item — event record shape, the fold that derives current state, the thirteen states and their legal transitions, and the `awaiting` block that makes `blocked` mean *blocked until*.

### Modified Capabilities

None. This repository has no specs yet; `backlog-item-format` is the first.

## Non-goals

Named because scope widening is this repo's recorded failure mode, and because two of these would settle open questions by accident.

- **Not adopting `bd`, and not rejecting it.** [[Q433]] is open. This change defines files in a directory; what manages them is a later question, and a format that assumes an owner would answer it silently.
- **No CLI, no MCP surface, no commands.** Reading and writing the format is the turn skill's job (dispatch-plan change 3).
- **No derived open-items index.** architecture.md §9 calls for one — a bounded index so a turn's read is not O(history). It belongs to whatever reads the whole backlog, which is not this change. Named here so it is not lost.
- **No claim protocol.** architecture.md §4's compare-and-swap push, the lease TTL and zombie reclamation are mechanism, not format. This change defines what a `claimed` event *looks like*, not who is allowed to write one or how the race is settled.
- **No board projection, no GitHub anything** (§7).
- **No compensation / undo item.** architecture.md §11 leaves it open; nothing here closes it.
- **No question format.** Concurrent change, YF-2's, in `questions/`. An `awaiting` block references a question by `ref` and says nothing about what lives at the other end.

## Impact

- **New**: `backlog/` — format spec, the worked fixture pair, `README.md` stating the append-only rule.
- **New**: `src/yosefactory/protocol/eventlog.py` (parse, order, dedup, apply a declared transition table, `terminal()`) and `src/yosefactory/protocol/backlog.py` (the item's declaration: thirteen states, the event table, the awaiting block), plus tests, so `make check` proves the acceptance criterion rather than a reader proving it by inspection. The fold is generic because [[D020]] makes a question and an item the same object in different states; the item vocabulary is its first consumer, not its shape.
- **Downstream**: dispatch-plan changes 3, 4 and 6 all read this format. Getting the event vocabulary wrong is cheap to fix now and expensive after three consumers exist.
- **Nothing existing is touched.** No source, no workflow definition, no ledger row.
