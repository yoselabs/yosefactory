## Context

See proposal.md — Why. Constraints that actually shape the format, all from architecture.md:

- §4 — the storage format is the concurrency design. Rewritten files conflict between concurrent writers; append-only line logs do not.
- §4 — mutual exclusion is a compare-and-swap push, not a lock, and it is *not* this change. The format only has to be able to record a claim.
- §9 — a turn's read is O(history), and this program has already hit that wall once in the corpus (`recall.py` exists because of it).
- §3 — `failed` and `falsified` are different kinds of event, and conflating them corrupts the one metric the program measures.
- §5 — every block carries a deadline and a pre-registered `on_timeout`.

Six worker sessions share one working tree with no branches, so anything that requires two writers to touch one file is a design smell here, not a theoretical concern.

## Goals / Non-Goals

**Goals:**
- A format a reader can verify by eye, without running anything.
- A fold that is total and deterministic: same lines, same state, regardless of file order.
- Corruption is loud. A format that degrades quietly is worse than one that refuses to read.

**Non-Goals:** see proposal.md — Non-goals. Two design-level additions:
- **No schema version field.** One operator, no deployed readers, and D002 means old lines stay readable by construction. A version field would be answered by guessing what future readers need; adding one later is itself an appended event.
- **No forward compatibility.** An unknown event fails the read rather than being skipped, deliberately. A skipping reader reports a state that never existed, which is exactly the "green stall" failure architecture.md §8 says this program reproduces.

## Decisions

### One file per item, not one log for the backlog

| | one shared log | file per item |
|---|---|---|
| concurrent writers, different items | same file, textual conflict | never touch the same file |
| read one item | scan everything (§9) | bounded by that item's own history |
| "what is ready?" | one read | directory scan |

Chosen: **file per item**, `backlog/items/<id>.jsonl`. The listing cost is real and is exactly what §9's derived open-items index exists to fix — and that index is a consumer's problem, deferrable, whereas a write conflict between two live workers is not. `git-appraise` stores per-review, not per-repo, for the same reason.

### JSONL, not TOML

The ledger uses TOML and this does not, which is worth justifying rather than glossing. TOML has no append-a-record-per-line form: appending a table means the file is parsed as a whole, and a half-written table breaks the entire file rather than one line. JSONL's unit of corruption is one line, and one JSON object per line is the exact shape §4 cites from `git-appraise`. Ledger rows are one file per run and never appended to after the fact, so they have no such pressure.

### Order by `ts`, tie-break on `event_id`, dedup on `event_id`

File order is not trustworthy: a git merge of two appends interleaves lines, and `merge=union` can duplicate them. So the fold sorts rather than trusting position, and dedups on `event_id`. This is `cat_sort_uniq` in three words, and it makes the log a CRDT for the cases that matter — concurrent appends to one item converge to the same state whichever order they land in.

Rejected: a per-item monotone `seq`. Two concurrent writers both compute `seq = n+1`, and now the tie-break field is itself the collision. Timestamps collide too, but the `event_id` tie-break is stable rather than semantically wrong.

**The honest limit:** two writers appending genuinely conflicting *transitions* (both claiming a `ready` item) converge to a deterministic state, but that state is one of the two claims arbitrarily, not a rejection. The format cannot fix that and does not pretend to — architecture.md §4's CAS push is what makes it impossible, and it is a later change. What this format guarantees is that the losing claim is still visible in the log.

### `backlog/.gitattributes` sets `*.jsonl merge=union`

Two appends to one item file are a conflict git can resolve correctly, given the fold is order-insensitive and deduplicating. Without it, a conflict marker lands in a data file and the next read fails. With it, the worst case is a duplicated line the fold already handles.

Trade-off accepted: `merge=union` on a file where order mattered would be dangerous. Order does not matter here, by the decision above — the two decisions hold each other up, and neither is safe alone.

### `terminal` is a predicate, not a state

**This overturns the dispatch, and it is flagged rather than applied quietly** (orchestration.md Article VII). architecture.md §3's `terminal: done · cancelled · poison · duplicate · abandoned` line reads as a legend over the five states above it; the graph draws thirteen nodes.

If `terminal` were a fourteenth state, some event would have to write it, and every terminal item would then have two representations — `done`, and `done`-then-`terminal` — that a fold cannot tell apart or reconcile. As a predicate it is one line, cannot drift, and nothing is lost: the name still exists and still means what §3 means by it.

Escalated and **accepted, 2026-08-16**: architecture.md §3 now carries the predicate and §10's "6 → 14" row reads "6 → 13". Thirteen states, `terminal` derived.

### The fold rejects illegal transitions instead of repairing them

A `claimed` on a `cancelled` item is a bug somewhere upstream. Reporting the item as cancelled-and-fine hides it; repairing it invents history. Failing the read makes it a foreign observation, which architecture.md §6 records as the only check class with a non-zero defect yield in this fleet.

### The fold is generic; the item vocabulary is its first consumer

Resolved 2026-08-16: the code lands in `src/yosefactory/protocol/`, and CLAUDE.md's structural rule is why — "unit of work, states, ledger row shape" is L1 by name, and the L1 test holds: if the record shape changed next month, existing rows would stop being comparable.

**And it is written generically, because [[D020]] says a cross-repo request *is* a question, and a question and an item are the same object in different states.** So there is one fold over an append-only event log, not one per kind:

```
protocol/eventlog.py    parse a .jsonl log · order · dedup · apply a transition
                        table · terminal() over a declared terminal set
protocol/backlog.py     the item's vocabulary: 13 states, the event table,
                        the awaiting block, frame validation
```

The fold never branches on "is this an item". It takes a declaration — states, terminal set, event→(from, to) table, per-event payload requirements — and applies it. `questions/` supplies a different declaration to the same fold.

Rejected: writing the fold against items now and generalising when the question format arrives. That is the shape that produces two folds which agree until they do not, and D020 says the two things are one object, so the divergence would be a modelling error rather than a refactor.

`protocol/` grows by these two modules and no more. The parser stays a parser: no discovery, no listing, no claiming, no CLI.

## Risks / Trade-offs

- **Directory scan to answer "what is ready?"** → accepted; §9's bounded index is the named fix and belongs to the consumer. Recorded here so the first turn that feels the cost knows it was priced.
- **`merge=union` silently duplicating lines** → dedup on `event_id` is what makes that harmless, so the two must not be separated. The spec states dedup as a requirement for this reason.
- **Timestamp skew between machines reorders the fold** → single operator, single machine today. If a second machine ever writes, this is the first thing that breaks; recorded rather than defended.
- **No compensation for a `done` item that shipped something bad** → architecture.md §11 leaves it open and this change does not close it. The format does not block it: a reverse item is an ordinary item with a `predecessor`.
- **The vocabulary is guessed ahead of its consumers** → three changes downstream read this format and none exists yet. Mitigation is that adding an event is additive and cheap; removing or renaming one is not, which is why the table is deliberately small and why `note` exists as the escape hatch for anything that is not a transition.

## Open Questions

Both open questions were resolved before apply, 2026-08-16: `terminal` is a predicate over thirteen states, and the fold lands in `protocol/` written generically per [[D020]]. Recorded in the decisions above rather than left here.

One remains genuinely deferrable: whether a question's declaration needs anything the fold's shape cannot express. It is answered by the concurrent `questions/` change reading this fold, not by guessing here — and if it forces a change, that is a re-sequence, not a silent widening of this one.
