## 1. `Places.transcripts`

- [x] 1.1 Add `transcripts: Path` to `Places` (`runtime/turn.py`), defaulting to `ledger` in every
      constructor (`Places.local`, `Places.nested`, `loop._places_for`) — never `Optional`; see
      design.md for why the `Optional`-with-`__post_init__` shape was rejected (`ty` cannot narrow
      it).
- [x] 1.2 `Places.nested` gains an optional `transcripts: Path | None = None` keyword argument;
      omitted, it resolves to that call's own `ledger`.
- [x] 1.3 Unit tests: `Places.local(repo).transcripts == places.ledger`;
      `Places.nested(ws).transcripts == places.ledger` when omitted;
      `Places.nested(ws, transcripts=X).transcripts == X`.

## 2. The executor seam

- [x] 2.1 `turn.Executor.__call__` gains a required `transcripts_dir: Path` parameter, alongside
      `runs_dir`.
- [x] 2.2 `executor.claude.run` gains an optional `transcripts_dir: Path | None = None` parameter
      (defaulting to `runs_dir`) and writes `<run_id>.stream.jsonl` there instead of under
      `runs_dir` unconditionally.
- [x] 2.3 `turn.take_turn`'s two executor call sites pass `transcripts_dir=places.transcripts`.
- [x] 2.4 Unit tests (`tests/executor/test_claude.py`): `transcripts_dir` given writes the stream
      there, not under `runs_dir`; omitted, falls back to `runs_dir` unchanged.

## 3. `ensure_transcripts_ignored`'s call site

- [x] 3.1 `take_turn`'s call becomes `runs.ensure_transcripts_ignored(places.transcripts,
      places.workspace)` — the function itself is not edited.
- [x] 3.2 Confirm (do not add if already covered) that `tests/runtime/test_runs.py`'s existing
      `test_the_guard_is_a_noop_when_the_ledger_lives_outside_the_workspace` already exercises the
      no-op path this change relies on.

## 4. CLI surface

- [x] 4.1 `runtime.loop` gains `--transcripts-dir`, matching the `--queue`/`--workspace` vocabulary.
- [x] 4.2 `_places_for` gains an optional `transcripts` parameter, applied via `replace()` after
      whichever `Places` shape is resolved; omitted, inert.
- [x] 4.3 `main()`'s in-function `executor` closure forwards `transcripts_dir` to `claude.run`.
- [x] 4.4 Unit tests: `_places_for` with a `transcripts` argument overrides the resolved shape's
      `transcripts`; omitted, inert (`transcripts == ledger`).

## 5. End-to-end receipt

- [x] 5.1 A test that fails before this change and passes after (`tests/runtime/
      test_places_transcripts.py`): under `Places.nested` with `transcripts` pointed outside the
      workspace, a turn's executor writes its raw transcript there, the file never enters the
      workspace's own tree, and `git status --porcelain` in the workspace reads clean.
- [x] 5.2 Verified fails-before by stashing the `src/` changes and re-running the new tests: they
      fail with `TypeError` (no `transcripts` field, no `transcripts_dir` parameter) rather than
      with an assertion — the seam did not exist, not merely behaved differently.

## 6. Validate, ADR, and archive

- [x] 6.1 `make check` passes (450 tests).
- [x] 6.2 Write `decisions/0019-*.md` — the `Places` seam ADR (non-obvious: the `Optional`-field
      shape was tried first and rejected by the type checker; a future worker would plausibly try
      it again without knowing why it fails).
- [x] 6.3 `openspec validate give-transcripts-their-own-place --strict` passes.
- [ ] 6.4 Commit with explicit pathspecs (Article V), confirm `git diff --cached` empty after.
- [ ] 6.5 Archive the change; re-run `make check` after archiving; confirm
      `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows only the declared MODIFIED block.
