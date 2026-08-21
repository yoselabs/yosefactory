## 1. Reword the invocation preamble

- [x] 1.1 `src/yosefactory/executor/invocation.py`: `Invocation.render()`'s vocabulary line becomes
      imperative — names the path, states it carries required fields, tells the agent to check it
      before writing. No field name added. Same position (skill, vocabulary, proposal path).

## 2. Reposition the reminder into the skill

- [x] 2.1 `workflows/turn-skill.md` gains one clause: check the vocabulary for the event's required
      fields before writing. Zero field names, zero event names added. Confirm word count stays
      under 120 (`test_the_skill_stays_short`, S098) — currently 94, target ~111.

## 3. Spec

- [x] 3.1 `turn-cycle`'s "The frame is not the channel for how a run is invoked" requirement gains a
      fourth scenario (delta in `specs/turn-cycle/spec.md`); header text and all three existing
      scenario titles kept verbatim. `openspec validate teach-the-done-event-schema --strict` passes.

## 4. The two $0 receipts

- [x] 4.1 `tests/protocol/test_backlog_fold.py`: new test parsing `backlog.VOCABULARY_SPEC`'s table
      live and asserting, for every event in `backlog.ITEM.rules`, the rule's required top-level
      field names are a subset of the documented `Carries` cell. Must fail if run against a
      deliberately-broken rule (verify by hand before finalizing, then revert the break — do not
      leave a skip or an xfail).
- [x] 4.2 `tests/runtime/test_turn_cycle.py`: new test running real `take_turn` against a
      `FakeExecutor`, asserting the recorded `Invocation`'s `render()` output carries the new
      directive text — proof by construction through the real, unconditional call site, not a
      hand-built `Invocation`.

## 5. Also in scope

- [x] 5.1 `Dockerfile:84`: `~/Documents/Knowledge/Projects/160-ai-factory/decisions/D023-*.md`
      becomes a bare corpus reference (`D023 §4`), no filesystem path, no username exposure risk in
      a public repository.

## 6. Verify

- [x] 6.1 `ruff check src/ tests/` and `ty check src/` clean.
- [x] 6.2 Full non-`live` suite passes (real-spend integration files excluded, unchanged from
      before this change).
- [x] 6.3 `openspec validate teach-the-done-event-schema --strict` passes on the change.
- [x] 6.4 `ledger/spend.jsonl` row count unchanged before/after (no live run, $0 spend).
