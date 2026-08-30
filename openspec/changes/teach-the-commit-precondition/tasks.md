## 1. Vocabulary spec

- [x] 1.1 Apply the `backlog-item-format` MODIFIED requirement from this change's spec delta to
      `openspec/specs/backlog-item-format/spec.md`, preserving the requirement's exact existing
      header text and every unrelated scenario byte-for-byte.
- [x] 1.2 Confirm the table rows, and every scenario except the two new ones, are unchanged from
      before this edit (`git diff` the requirement block).

## 2. Skill file

- [x] 2.1 Rewrite `workflows/turn-skill.md`: trim filler from existing sentences ("the path given
      as", "for the fields your event requires", "anything under", "that says so rather than an
      optimistic one", "instead of one object" and similar), preserving every distinct instruction
      currently present.
- [x] 2.2 Add one short sentence: commit your own work first, explicit paths, never `git add -A`,
      or `done` is refused.
- [x] 2.3 `python3 -c "print(len(open('workflows/turn-skill.md').read().split()))"` — confirm the
      count is under 120 before running the test.
- [x] 2.4 Folded in mid-apply (director-flagged): reword "Do not edit anything under `backlog/`"
      to name no literal path — the wording predates D033 and is wrong under `Places.nested`
      (`.factory/backlog/`, not top-level `backlog/`). New wording: "the caller's own bookkeeping."

## 3. Regression test

- [x] 3.1 In `tests/runtime/test_turn_cycle.py`, beside `test_the_skill_stays_short`, add a test
      asserting the skill text contains the commit instruction (e.g. checks for `"commit"` and
      `"git add -A"` substrings) — guards presence only; does not and cannot test agent obedience.

## 4. Verify

- [x] 4.1 `make check` (in container, per this repo's Docker-only execution rule). 449 passed, 11
      deselected; lint/type/citations all green.
- [x] 4.2 `uv run pytest tests/runtime/test_turn_cycle.py -k "skill" -v` (in container) — both the
      word-count test and the new presence test pass (2 passed).
- [x] 4.3 `openspec validate teach-the-commit-precondition --strict` passes.
- [x] 4.4 Read the full diff of `workflows/turn-skill.md` once more before committing — confirmed
      every existing instruction survives, compressed, plus the two new/reworded lines.
