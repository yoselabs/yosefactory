## Why

Found immediately after archiving `commit-the-spend-row-inside-the-turn` (2026-08-22), by rerunning
`openspec validate --specs --strict` and actually reading its output rather than trusting "26
passed" as sufficient — that check is structural (does every requirement parse, is every scenario
well-formed), not a content-consistency check against the code it describes, and it cannot see this
gap by construction.

`openspec/specs/claude-executor/spend-ledger/spec.md`'s "Every completed invocation appends a
durable spend row" requirement states, verbatim: *"`executor/claude.py::run()` SHALL append one row
to a spend ledger after every invocation ... at a path resolved from this module's own location."*
`commit-the-spend-row-inside-the-turn` removed that call from `claude.py` entirely — recording moved
to `runtime/turn.py::_finish`, and the path resolves from `Places` (`turn.spend_log_for`), not from
`spend.py`'s own module location. The requirement's text is now false about the code it governs: a
future reader of this spec alone would look for a call site that no longer exists, at a path
resolution rule that is no longer what real turns use.

This is exactly the case `orchestration.md` Article XIV's own amendment describes: *"A MODIFIED that
corrects a statement which has become false necessarily deletes it — additive correction is
impossible when the old sentence is the defect."* No promotion entity governs this correction; it is
the direct, immediate consequence of the change just archived, caught by re-checking rather than by
trusting the strict-validate pass as proof of nothing left to fix.

## What Changes

- **`openspec/specs/claude-executor/spend-ledger/spec.md`**: one MODIFIED requirement. Same title
  (`Every completed invocation appends a durable spend row` — unchanged, so the archiver's
  header-text matcher can locate it; `RENAMED` is not in play here). Body corrected: the writer is
  now `runtime/turn.py::_finish`, reading `RunResult.usage.total_cost_usd` from whichever `Executor`
  ran (not only `claude.py`'s), and the path resolves via `turn.spend_log_for(places)` — inside
  `places.queue`, not from `spend.py`'s own module location. The "known limitation" paragraph about
  `SPEND_LOG`'s `repo_root()` resolution is corrected to describe what it actually still governs
  (the package-relative default for a caller with no `Places` in view) rather than what every real
  turn does.
- **No code changes.** `commit-the-spend-row-inside-the-turn`'s implementation is correct and
  already tested; this change corrects only the spec text that now disagrees with it.

## Non-goals

- Re-litigating `commit-the-spend-row-inside-the-turn`'s design. That change's `design.md` and
  ADR-0011 stand; this is a spec-text correction, not a design change.
