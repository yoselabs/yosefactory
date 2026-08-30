# .factory

**This repository's queue. Machine-written. Do not edit by hand.**

Under K decision D033 each workspace's queue lives inside that workspace's own repository, so an
item in this directory *is* this repository's item and no other workspace can see it or pay for it.
D034 keeps the credential, the schedule and the transcripts in the private runner and leaves
everything below here local. A turn commits its work and its bookkeeping in the same commit.

This repository is the machine as well as a workspace: the code that reads this directory is the
code in `src/` beside it. That is the point — issues opened here are how the factory is asked to
improve itself.

## The shape, and what fixes each path

Every name here is a constant in this repository's own `src/yosefactory/runtime/turn.py`, read
relative to the queue root (`Places.nested`, whose `queue_subdir` defaults to `.factory`). They are
not conventions this file is free to change.

```
.factory/
  backlog/items/*.jsonl   ITEMS      one work item, one file, one JSON event per line
  questions/*.jsonl       QUESTIONS  a blocked turn's question, resolved by an answer event
  ledger/runs/            RUNS       one record per turn: <slug>.start, then <slug>.json
  ledger/spend.jsonl                 one row per model invocation, joined to a run by run_id
```

`ITEMS`, `QUESTIONS` and `RUNS` are literal in `turn.py` (`RUNS` = `ledger/` + `runs.STREAM_DIRNAME`);
`spend.jsonl` is where `spend_log_for()` resolves it, as `places.ledger.parent / "spend.jsonl"`.

The item format is specified in `src/yosefactory/protocol/backlog.py` — the event table the fold
enforces. A second copy of it is a second thing to be wrong, so there is none here.

**Not the same directories as the root-level `backlog/`, `questions/` and `ledger/`.** Those are
`Places.local`'s: one repository playing every role, which is how this platform's own development
turns have always run. This nested queue is `Places.nested`'s, and the two never merge. Raw
transcripts under `.factory/ledger/runs/` are excluded per-clone by `ensure_transcripts_ignored`
writing to `.git/info/exclude`, not by the root `.gitignore`, whose `ledger/runs/*.stream.jsonl`
rule is anchored at the repository root and does not reach here.

Two properties that decide how anything here may be touched:

- **Append-only.** Nothing is edited, reordered or deleted. An item is closed by appending the event
  that closes it.
- **The state is the fold.** `state`, `lease`, `awaiting` and the frame are replayed from an item's
  own events. Nothing stores them.

## How work gets in

**Open a GitHub issue on this repository.** That is the whole intake path: the runner ingests new
issues into items here, and only from a login in `config.json`'s `users.allowed`. Hand-writing a
file in `backlog/items/` bypasses ingest, is picked up by the next turn as if a human had never been
involved, and spends real quota on it.

An empty `backlog/items/` is the normal state and is not a fault. The pre-flight check globs it,
finds nothing, reports `ready=false` and skips the run without paying for anything.

## `make check`

`.factory/` is data, not source. Nothing in the repository's own gate reaches it: `ruff` and `ty`
run against `src/` and `tests/`, `pytest`'s `testpaths` is `tests`, `codespell` takes an explicit
path list, and the packaging backend builds `src/yosefactory` only. No exclusion was needed, and
none should be added — a queue directory must never be able to fail the machine's own gate.
