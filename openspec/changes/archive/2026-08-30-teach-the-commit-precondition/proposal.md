## Why

`workflows/turn-skill.md` never tells the agent to commit its own work before proposing `done`.
`yoselabs/factory-state` run `33318136736` (2026-08-30) did the work correctly, spent $0.3496, and
then failed `verify.gate`'s `tree_clean` check — nothing ever told the agent committing was part of
the job. `grep -niE "commit|git add|stage" workflows/turn-skill.md` returns zero hits.

No K project 160 promotion names this — there is none. This is a director-dispatched fix from an
operational incident (a real unattended run's failure), not a promotion from the design record.

## What Changes

- `openspec/specs/backlog-item-format/spec.md`: the existing `done` requirement gains a scenario —
  the tree must be clean before `done`, the agent commits its own work with explicit pathspecs, and
  `git add -A` is named and forbidden (it can sweep the platform's own `.factory/` bookkeeping into
  the agent's commit under D033's nested-queue layout).
- `workflows/turn-skill.md`: a terse reinforcement of the same obligation, fitted inside the
  existing <120-word budget (`test_the_skill_stays_short`) by trimming filler from existing
  sentences, not by widening the budget.
- `workflows/turn-skill.md`, folded in: the pre-existing "Do not edit anything under `backlog/`"
  line named a literal path that predates D033 and is wrong under a nested queue (the real
  bookkeeping directory is `<workspace>/.factory/`, not top-level `backlog/`) — reworded
  layout-agnostically ("the caller's own bookkeeping") so it stays true under `Places.local`,
  `Places.nested`, and any future variant, rather than naming a path that already drifted once.
- One regression test extending `tests/runtime/test_turn_cycle.py` near `test_the_skill_stays_short`,
  asserting the commit instruction's wording is present in the skill file — guards against silent
  removal (this repo has already lost one prose convention this way: the harness's
  `Co-Authored-By: Claude` habit, per `orchestration.md`'s "Commit attribution" section). This does
  **not** and cannot test that an unattended agent obeys the instruction — said plainly, not papered
  over.

No code under `src/yosefactory/` changes. `ADR-0005` ("agent checkpoints, platform delivers") is not
reopened: it already decided the agent commits its own work and the platform only amends `HEAD`'s
trailers after the gate passes; this change teaches that existing, correct division of labour to the
agent, it does not alter it.

## Capabilities

### Modified Capabilities

- `backlog-item-format`: the `done` requirement's scenario set gains one scenario describing the
  commit precondition and the `git add -A` hazard, alongside the existing `effects`/`verified_by`
  field requirement.

## Non-goals

- Not reopening ADR-0005 or moving commit responsibility to the platform. No evidence surfaced that
  "agent checkpoints, platform delivers" is wrong — only that nobody told the agent its half.
- Not scoping `verify.tree_clean` away from `.factory/`. Traced: `.factory/`'s own commits (claim,
  started) land before the executor is ever invoked, so `.factory/` is not what went dirty in the
  observed failure — the agent's own uncommitted file was. No fix needed there.
- Not building a mechanized check that an agent actually commits before proposing `done` — that
  already exists and is exactly what caught this run (`verify.tree_clean`, refusing correctly). This
  change is about telling the agent, not about a second enforcement layer.
- Renaming or restructuring the queue directory itself, or touching any code path in
  `src/yosefactory/`. The `backlog/` wording fix above is a rewording of skill prose only — the
  underlying `ITEMS`/`QUESTIONS` constants and `Places` classmethods are untouched.

## Impact

- `workflows/turn-skill.md`
- `openspec/specs/backlog-item-format/spec.md`
- `tests/runtime/test_turn_cycle.py`
