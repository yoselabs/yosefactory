## 1. Protocol — `backlog-item-format`

- [ ] 1.1 Add `gate_rejected` to `backlog.ITEM.rules`: `Rule(frozenset({"doing"}), None, required=(("report",), ("attempt",)))`.
- [ ] 1.2 Add `backlog.context(item: FoldedLog) -> dict[str, Any]`, folding the four D030 sources
      (`gate_rejected`, `unblocked.resolution.answer`, `failed`, `released`/`reclaimed`),
      last-one-wins per source, same pattern as `frame()`.
- [ ] 1.3 Update `VOCABULARY_SPEC`-mirrored table (`openspec/specs/backlog-item-format/spec.md`)
      only via this change's spec delta — do not hand-edit the promoted spec.

## 2. Runtime — gate rejection reaches the item

- [ ] 2.1 In `_dispose`'s `done` branch (`runtime/turn.py`), on `not gate.passed`: append
      `gate_rejected` (`report=gate.report()`, `attempt` read from
      `backlog.lease(backlog.load(item_path))`) to `item_path` before `return failed(...)`.
- [ ] 2.2 Confirm the append lands in the same commit as the existing `failed(...)` turn record —
      `item_path` is already in `touched`/`paths` for that branch; no new commit call needed.
- [ ] 2.3 Confirm `_poison_if_exhausted` is not reachable from this path (it is not — the branch
      returns before `folded = append(item_path, backlog.ITEM, event, ...)` is reached) and that no
      attempt-budget consumption results from a `gate_rejected` alone.

## 3. Runtime — answer text reaches the item

- [ ] 3.1 In `apply_answers()` (`runtime/turn.py`), read the closing question record's `answer`
      field (`question.outcome(asked)`) and include it in the `unblocked` event's `resolution` dict
      when present (`answered` outcome only — `timed_out`/`cancelled` carry no answer text).
- [ ] 3.2 No change to `question.py` — the canonical answer stays in the question log; the item's
      copy is written, never re-read to make a second decision.

## 4. Executor seam

- [ ] 4.1 `Executor.__call__` (`runtime/turn.py`): add keyword-only
      `context: Mapping[str, Any] | None = None`, positioned after `frame`.
- [ ] 4.2 `take_turn`'s acting branch: compute `context = backlog.context(backlog.load(item_path))`
      beside the existing `frame = backlog.frame(...)` line; pass both to `executor(...)`.
- [ ] 4.3 `take_turn`'s planning branch: pass no context (planning has no item to fold one from).
- [ ] 4.4 `executor/claude.py`'s `render()`: accept `context: Mapping[str, Any] | None = None`;
      when non-empty, render a labelled block after the frame's three lines and before
      `invocation.render()`'s plumbing lines. Empty/`None` context renders nothing.
- [ ] 4.5 `executor/claude.py`'s `run()`: thread `context` through to `render()`.

## 5. Tests

- [ ] 5.1 `tests/protocol/test_backlog_fold.py`: `gate_rejected` legal from `doing`, illegal
      elsewhere; does not change state; repeated `gate_rejected` does not poison.
- [ ] 5.2 `tests/protocol/test_backlog_fold.py` (or new): `backlog.context()` — each of the four
      sources folds correctly in isolation and in combination; `note` never appears; empty log
      folds to `{}`; last-one-wins when a source repeats.
- [ ] 5.3 `tests/protocol/test_turn.py` / `tests/runtime/test_turn_cycle.py`: a rejected `done`
      proposal appends `gate_rejected` to the item in the same commit as the turn's `failed` record;
      the item stays `doing`; a second turn against the same item receives the report in `context`
      and a byte-identical `frame` to the first turn's.
- [ ] 5.4 A test exercising `apply_answers()` end to end: an `answered` question's text appears in
      the resulting `unblocked.resolution.answer`, and in the next turn's folded `context`.
- [ ] 5.5 `render()` unit test: context block appears between frame lines and invocation lines when
      context is non-empty; nothing extra appears when it is empty.

## 6. Close

- [ ] 6.1 `make check` (lint, ty, test, citations) green.
- [ ] 6.2 `openspec validate carry-inherited-context-into-the-turn --strict` passes on the change.
- [ ] 6.3 Decide, at archive time, whether this change's build-time choices (the new event's
      no-state-change shape, answer-copied-not-referenced) need a `decisions/000N-*.md` ADR per
      `openspec/config.yaml`'s non-obvious test — likely yes for the copy-vs-reference call.
- [ ] 6.4 Archive. Confirm `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows only additions
      inside the declared MODIFIED/ADDED blocks (deletions = 0, or every deletion is inside a block
      named in the commit message).
