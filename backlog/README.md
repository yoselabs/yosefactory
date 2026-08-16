# backlog

One work item, one file: `backlog/items/<id>.jsonl`, one JSON event object per line.

**Append-only.** Nothing here is ever edited, reordered or deleted (D002). An item is closed by
appending the event that closes it, never by rewriting what it said before.

**The state is the fold, not a field.** `state`, `lease`, `awaiting`, `successor`, `survivor`,
`priority` and the frame itself are all derived by replaying the item's own events. Nothing stores
them. That is what makes concurrent writers safe without a lock: a rewritten file conflicts, an
append-only log does not.

If the format ever tempts you to mutate a line in place, the format is not the problem.

## Reading one

```python
from yosefactory.protocol import backlog

item = backlog.load("backlog/items/itm-0007.jsonl")
item.state          # 'falsified'
item.terminal       # False — terminal is a predicate over five states, not a state
backlog.frame(item) # goal · method · assumptions (D019)
```

The fold is generic (`protocol/eventlog.py`) and knows nothing about items; the item's thirteen
states and its event table are a declaration in `protocol/backlog.py` (D020 — a question and an item
are the same object in different states, so there is one fold).

## What is here

- `items/` — the items. Empty until the turn skill writes one.
- `fixtures/falsified-round-trip/` — a falsified item and its successor, written by hand. The
  acceptance criterion for this format, readable without running anything: the closed item keeps its
  frame and full trail, the successor names what falsified its predecessor, and the link resolves in
  both directions.

## The contract

`openspec/specs/backlog-item-format/spec.md` — the states, the event table, and what fails a read.
An unknown event, an illegal transition, a malformed line or a block with no deadline all fail the
read rather than being skipped: a reader that silently ignores what it does not understand reports a
state that never existed.
