## Why

[[D030]] (`~/Documents/Knowledge/Projects/160-ai-factory/decisions/D030-*.md`), answering [[Q436]]:
the frame stays a statement of the task; a second channel, folded from the item's own event log,
carries what the attempt before this one produced. Two confirmed defects motivate it, both read from
code rather than from a failure (eleven CI runs, zero gate rejections, zero live answers):

- **[[S1037]].** `runtime/turn.py` rejects a `done` proposal (`if not gate.passed: return
  failed(gate.report())`, `_dispose`) before the `append(item_path, ...)` twelve lines below is ever
  reached. The gate's report reaches the `TurnRecord` in the ledger; the item's own log gets
  nothing. The next attempt re-reads the same `frame` and is byte-identical to the one that just
  failed.
- **[[S1038]].** `apply_answers()` appends `unblocked` with `resolution: {"qid": ..., "by": <event
  name>}` — a pointer. The answer text itself is written by `board/inbox.py`'s `_apply_answer` to
  the *question* log, never to the item. `backlog.frame()` folds only `created`/`frame_amended`, so
  the text never reaches the executor even though it lives one file away.

Root: `backlog.frame()` is the executor's only channel (`turn.py:738`), and it folds exactly two of
the eight information-bearing events the format defines. `backlog.awaiting()` exposes the blocked
state and is not called from `runtime/turn.py` — it *is* called from `board/inbox.py`'s
`_apply_answer`, so the Q436/S1038 write-ups' framing of it as unreached is narrower than "dead":
it has a live caller, just not the one they were tracing.

## What Changes

- **A new `gate_rejected` event** (`backlog-item-format`), legal from `doing`, no state change,
  carrying `report` (the gate's own `GateResult.report()` string) and `attempt` (read back from the
  item's own `claimed` lease via `backlog.lease()`, never threaded as a fresh parameter). Appended by
  `_dispose` immediately before the existing `return failed(...)` on gate rejection, so it lands in
  the same commit the failed turn already makes (`item_path` is already in that branch's `touched`
  list). No existing rule in the table fits: everything reachable from `doing` either changes state
  (`blocked`, `falsified`, `failed`, `needs_split`, `done`) or is `frame_amended`/`note`, both
  excluded by D030 for this purpose.
- **`unblocked.resolution` gains an `answer` key** carrying the answer's text, written by
  `apply_answers()` at the moment it reads the question's own `answered` record — not read
  cross-file at fold time. D030 requires the context channel to be "folded from the item's own event
  log"; a fold that reached into the question log to resolve `answer` at read time would make the
  channel depend on two logs, not one. `resolution.qid`/`resolution.by` are unchanged.
- **`backlog.context(item) -> dict`**, a new pure fold over the item's own log alongside
  `backlog.frame()`, folding exactly D030's four sources (last-one-wins per source, same pattern as
  `frame()`): `gate_rejected` → `report`+`attempt`; `unblocked.resolution.answer` (when present) →
  the text; `failed` → `reason`/`retryable`/`attempt`; `released`/`reclaimed` → `reason`. `note` is
  not folded — deliberately, per D030: legal in any state, unbounded free text, and the thing that
  keeps this channel bounded is that nothing but these four sources feeds it.
- **`Executor.__call__` gains a keyword-only `context: Mapping[str, Any] | None = None`**, passed
  alongside `frame` at the one call site that has an item (`take_turn`'s acting branch); the planning
  branch has no item and passes nothing (`None`, folding to `{}`). `claude.py`'s `render()` accepts
  the same parameter and appends a rendered block after the frame's three fields and before
  `invocation.render()`'s plumbing lines — so the ordering `goal/method/assumptions` →
  `context` → `skill/vocabulary/proposal-path` keeps epistemic content ahead of plumbing, matching
  the existing frame-then-invocation convention.
- **`backlog.awaiting()` stays as-is.** It is not dead — `board/inbox.py`'s `_apply_answer` reads it
  today to find the question a blocked item is waiting on — and this change gives `runtime/turn.py`
  no new reason to call it, since `context()` reads `unblocked`/`gate_rejected`/`failed`/
  `released`/`reclaimed` directly rather than through the awaiting block.

## Non-goals

- No compaction rule for the context channel. D030's revisit trigger — "measured larger than the
  frame on three items" — is what would force one; nothing here pre-builds it.
- No change to what `frame_amended` means or when it fires.
- No new question kind, no change to `apply_answers()`'s unblocking logic beyond the one new field.
- No UI, no board-facing rendering of inherited context — this is executor-facing only.

## Entity ids acted on

[[D030]], [[S1037]], [[S1038]], [[Q436]] — read, not re-derived. This proposal implements D030's
ruling; it does not revisit whether frame-as-task was the right call.
