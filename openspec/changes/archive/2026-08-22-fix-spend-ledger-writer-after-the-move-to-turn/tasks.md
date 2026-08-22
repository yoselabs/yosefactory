## 1. Correct the spec

- [x] 1.1 `openspec/specs/claude-executor/spend-ledger/spec.md` delta (this change): MODIFIED
      requirement, same title, corrected body and scenarios naming `runtime/turn.py::_finish` as
      the writer and `spend_log_for(places)` as the path resolution.

## 2. Validate and archive

- [x] 2.1 `openspec validate fix-spend-ledger-writer-after-the-move-to-turn --strict` passes.
- [x] 2.2 `openspec archive fix-spend-ledger-writer-after-the-move-to-turn`.
- [x] 2.3 `git diff --stat -- openspec/specs/claude-executor/spend-ledger/spec.md`: 37 insertions,
      21 deletions, all inside the block this change declares MODIFIED (the stale
      `executor/claude.py::run()` text), named here and in the commit message, per Article XIV's
      amendment.
