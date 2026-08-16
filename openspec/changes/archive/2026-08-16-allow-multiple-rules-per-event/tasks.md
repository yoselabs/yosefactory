## 1. Confirm the ground before changing it

- [x] 1.1 Confirm no committed item log carries a `blocked` event with `awaiting.deadline`
      (`grep -rn "awaiting" backlog/ ledger/`), so removing the field migrates no stored data
- [x] 1.2 Record the baseline: `make check` green, and the collected test count, so "none may
      break" is measured against a number rather than a memory — **130 collected (129 passed, 1
      xfailed)**, not the 114 the dispatch remembered; other workers had added tests since

## 2. The fold accepts several rules per event

- [x] 2.1 `Declaration.rules` becomes `Mapping[str, Rule | tuple[Rule, ...]]`; normalize a bare
      `Rule` to a one-element tuple where the rules are read, not in the dataclass
- [x] 2.2 Replace `_check_from` with rule selection: position 0 takes the first rule with no
      from-check; otherwise the first rule whose `from_states` matches wins
- [x] 2.3 Matching is `ANY` → always, `ANY_NON_TERMINAL` → state not in `declaration.terminal`,
      `frozenset` → membership. The blanket terminal guard is gone from the match path (design D2)
- [x] 2.4 Selection failure keeps both existing messages byte-identical: the terminal wording when
      the current state is terminal, otherwise `legal from:` with the union of all named states,
      sorted
- [x] 2.5 `_check_payload` and `_target` take the *selected* rule (design D3)
- [x] 2.6 Update the module docstring: what "loud" now means, given that a declared absorption is
      not silence

## 3. Tests for the fold itself

- [x] 3.1 Two rules, first match wins: the same event transitions from one state and no-ops from
      another
- [x] 3.2 An event whose rules match no current state fails, with the terminal wording when the
      state is terminal and the `legal from:` wording otherwise
- [x] 3.3 Per-rule payload: the transitioning rule enforces its `required`, the absorbing rule
      requires nothing, in one log
- [x] 3.4 A single bare `Rule` still works unchanged — the item declaration's own tests are the
      real evidence, so assert it once directly and rely on them for the rest

## 4. The question declaration, committed

- [x] 4.1 Add `src/yosefactory/protocol/question.py`: `STATES`, `TERMINAL`, `QUESTION`, mirroring
      `backlog.py`'s shape — data plus the declaration, no parser
- [x] 4.2 `timed_out` carries two rules in order: `awaiting` → `timed_out` requiring `policy` and
      `answer`, then the terminal set → no state change requiring nothing
- [x] 4.3 `noted` is legal from any state (`ANY`), matching the spec and the item declaration — not
      the `awaiting`-scoped snippet in `questions/examples/README.md`
- [x] 4.4 `asked` keeps requiring `deadline` and `on_timeout` with the `on_timeout` pattern: the
      question is now their only owner

## 5. Tests over the fixtures

- [x] 5.1 `tests/protocol/test_question_fold.py` folds every file in `questions/examples/` and
      asserts the state each one's README row claims
- [x] 5.2 Assert the acceptance pair explicitly: answering `3f9a2c1d` leaves `b7e40a52` `awaiting`
- [x] 5.3 Assert a second `answered` under a different `event_id` still fails the read
- [x] 5.4 Assert `noted` after a question closed is legal and changes nothing

## 6. The fifth fixture — the race, on disk

- [x] 6.1 Write `questions/examples/q-<new>.jsonl`: `asked`, `answered` at T, `timed_out` at T+1s
      from `loop:yosefactory/sweeper` carrying the policy it fired under
- [x] 6.2 Assert in `test_question_fold.py` that it folds to `answered` **and** that the
      `timed_out` record is present in `FoldedLog.records` — retention is the point, not tolerance
- [x] 6.3 Add its row to `questions/examples/README.md`, correct the declaration snippet there
      (`noted`, the two `timed_out` rules), and replace the "not committed anywhere yet" note with
      a pointer to `protocol/question.py` and the test

## 7. `awaiting` stops repeating the question's fields

- [x] 7.1 `backlog.py`: drop `deadline` and `on_timeout` from `_AWAITING_FIELDS` only. **Keep** the
      `awaiting.on_timeout` pattern — it validates an item-kind block and is silent on a
      question-kind one, since patterns are skipped when the field is absent
- [x] 7.2 Rewrite the one test that asserts the removed requirement
      (`test_a_block_without_a_deadline_fails_the_read`): a question-kind block without a `deadline`
      now reads, and the bound is the question's. The `on_timeout` pattern test and the
      three-policies test survive untouched — confirm rather than assume
- [x] 7.3 Add a test that an item-kind block carries its own `deadline`/`on_timeout` and folds, so
      the S172 bound for item-on-item blocks is asserted rather than assumed
- [x] 7.4 Update the module docstring of `test_backlog_blocked_until.py`: blocked-until is still the
      rule; the *until* lives on the question where one exists and on the block where none does
- [x] 7.5 Update `questions/README.md`'s declaration section for the two `timed_out` rules and for
      ownership of `deadline`/`on_timeout` being the question's wherever a question exists

## 8. `failure_kind` — why a turn failed, as a queryable field

- [x] 8.1 Add `FailureKind` to `protocol/turn.py`: the nine values of design D7's table, with the
      docstring stating that this set is executor-facing and expected to change, unlike `Outcome`
- [x] 8.2 Add `failure_kind: FailureKind | None = None` to `TurnRecord`; keyword-defaulted so no
      existing writer — `runtime/supervise.py` included, and it is not mine — needs touching
- [x] 8.3 `__post_init__` rejects a `failure_kind` on any outcome other than `failed`, naming both
      fields, and rejects a value outside the set
- [x] 8.4 `to_dict` emits `failure_kind` as its value or `None`; `from_dict` accepts a missing key
      as null and rejects an unknown value naming the valid ones
- [x] 8.5 Tests in `tests/protocol/test_turn.py`: the starved-versus-broken pair reads apart on the
      field alone; a kind on `advanced` is rejected; an unknown kind is rejected; a payload with no
      `failure_kind` key round-trips; a harness kill with null kind is well-formed
- [x] 8.6 Test that every `executor.outcome.FailureKind` value has a `failure_kind` counterpart, so
      a new vendor reason breaks a test rather than a record. Import only — `executor/` is another
      worker's directory and is not edited here
- [x] 8.7 Leave `RunResult.note()` alone. Retiring the interim workaround belongs to the executor's
      owner; report that the field has landed

## 9. Close out

- [x] 9.1 `openspec validate allow-multiple-rules-per-event --strict` passes
- [x] 9.2 `make check` green; collected test count is not below the 1.2 baseline
- [x] 9.3 Commit with explicit pathspecs only, `PREK_ALLOW_NO_CONFIG=1`, citing M600 and the
      constitution's Article V form (`git commit -- <paths>`, `git add` first for new files, and
      `git restore --staged <new>` if the commit is rejected)
- [x] 9.4 Report to the director: the change, what the corrected `awaiting` rule cost, the
      `cancelled` candidate not built, `who`/`nudge_at` left alone, the stale spec pointer in
      `questions/README.md`, the `failure_kind` mapping YF-4's successor must wire, and the signal
      content for the director to author against M600 (do not write to P160)

## Outcome

- Baseline 130 collected (129 passed, 1 xfailed) → **165 collected, 165 passed, 0 failed**. Nothing
  broke. The baseline's single xfail is gone from `tests/executor/test_integration.py`, which another
  worker fixed in the same window — not this change.
- `make ty` green. `ruff` green over every path this change touches.
- **`make check` cannot go green from here, and not because of this change.** The lint target runs
  `ruff check src/ tests/` unscoped, and `src/yosefactory/runtime/turn.py` — untracked, another
  worker's file, created during this apply — fails `RUF100`. Article IV forbids fixing it and
  Article II requires reporting it. This is [[S184]] arriving exactly as recorded.
- 9.3's commit is the first real `git commit` any worker has run tonight, so it is also the live test
  of the permission posture recorded in `orchestration.md`.
