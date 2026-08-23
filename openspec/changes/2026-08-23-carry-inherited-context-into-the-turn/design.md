## Context

D030 rules the shape; this change fills in the four points D030 left to the build:

1. what event carries a gate rejection onto the item,
2. how the answer text crosses from the question log to the item,
3. the executor signature and prompt rendering,
4. what happens to `awaiting()`.

## Decision 1 — the gate-rejection event

**New event: `gate_rejected`.** `Rule(frozenset({"doing"}), None, required=(("report",), ("attempt",)))`
— legal from `doing`, no state change (same shape as `frame_amended`, `priority_set`, `note`).

Checked against the existing table before adding anything: every event reachable from `doing` either
changes state (`blocked`→blocked, `falsified`→falsified, `failed`→failed, `needs_split`→needs_split,
`done`→done) or is one of the two D030 excludes for this purpose (`frame_amended`, `note`). A gate
rejection is not a failure of the *turn* in the state-machine sense — the item must stay `doing` and
retryable within the same attempt budget the way it already implicitly does today (no event at all
was written) — so reusing `failed` would burn the attempt counter and misrepresent an unwritten
`done` as an agent-reported failure. Nothing in the table fits; D030 explicitly permits adding one
here.

`attempt` is not threaded as a new parameter through `_dispose`/`failed()`. It is read back from
`backlog.lease(backlog.load(item_path))["attempt"]` at the point of rejection — the same lease the
`claimed` event already recorded for this attempt. Re-deriving from the log rather than passing a
fresh argument keeps `_dispose`'s signature untouched and matches `claims()`/`failure()`'s existing
pattern of computing facts from the fold rather than from a thread of function arguments.

## Decision 2 — the answer text's route

**Copied onto the item at `unblocked` time**, not read cross-file at fold time.

D030's own wording is the deciding fact: the context channel is "**folded from the item's own event
log**." A fold that resolved `resolution.qid` against the question file at read time would make the
context depend on two files, contradicting that sentence — and would leave `backlog.context()` no
longer a pure function of one `FoldedLog`, unlike every other reader in this module.

`apply_answers()` already reads the closing question record (`question.outcome(asked)`) to decide
whether to unblock at all. Attaching the raw `answer` field to the same `unblocked` append it already
writes costs one more field, not a new read. The value that lands in the item's own log is the
answer's text as of the moment it closed — a copy is real duplication (question log keeps the
canonical `answered` record; item log now keeps a read-only echo of the same string), and duplication
that is written once and never re-read for a second decision is exactly the kind D030 accepts as the
cost of a channel that folds from one file.

## Decision 3 — executor signature and rendering

`Executor.__call__` gains one keyword-only parameter: `context: Mapping[str, Any] | None = None`,
placed after `frame` and before the isolation/limits parameters, matching where `invocation` already
sits — plumbing-adjacent, not part of the falsifiable frame.

`take_turn`'s acting branch computes `context = backlog.context(backlog.load(item_path))` right
beside its existing `frame = backlog.frame(...)` line and passes both. The planning branch has no
item and passes nothing; `render()` treats an absent/empty context as before (no block emitted).

`claude.py`'s `render(frame, context=None, invocation=None)` renders context, when non-empty, as a
labelled block between the frame lines and the invocation lines:

```
goal: ...
method: ...
assumptions: ...

Inherited context from a prior attempt:
- gate rejected: <report>
- answered: <text>
- prior attempt failed: <reason> (retryable: <bool>)
- previous attempt ended: <released/reclaimed reason>

Follow the skill at ...
```

Ordering matters and is deliberate: frame (epistemic, D019) first, context (what happened) second,
invocation (plumbing) last — the same "content before plumbing" order the frame/invocation split
already establishes, extended rather than reinvented.

## Decision 4 — `awaiting()`

**Left as-is, not removed, not newly called from `runtime/turn.py`.**

Q436 and S1038's write-ups describe it as "never called anywhere in `runtime/turn.py`" — true, and
distinct from dead. `grep` shows one live caller: `board/inbox.py`'s `_apply_answer`, which reads
`backlog.awaiting(item)` to find the `qid` a blocked item is waiting on before writing the question's
`answered` record. That is exactly the job `awaiting()` was built for and it is still the only way
`_apply_answer` locates the right question file.

`context()` does not need it: the four sources it folds (`gate_rejected`, `unblocked.resolution`,
`failed`, `released`/`reclaimed`) are read directly off the item's event stream, not through the
current `awaiting` block (which is only present while `blocked`, and `context()` runs against
whatever state the item is in). So this change gives `runtime/turn.py` no new reason to call it
either. The corrected finding, carried back to K: **not dead — one caller, in `board/inbox.py`, doing
its documented job.**
