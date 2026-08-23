## Why

S237 (K project 160, both trail entries): the ignore rule for raw transcripts
(`ledger/runs/*.stream.jsonl`) lives only in yosefactory's own `.gitignore` — correct there, but
yosefactory is never the workspace the `done` gate inspects. Under `Places.local(repo)`, the ledger
nests inside the workspace `verify.tree_clean` checks, and a foreign workspace (any real target
repo, e.g. `a2web`) has no such rule. A turn's own transcript then reads as the agent's uncommitted
work — measured live in `turn-20260823T114551Z-27b349fb`, where an agent that had committed
correctly was graded as having failed to commit.

## What Changes

- A new `runs.ensure_transcripts_ignored(runs_dir, workspace)` writes the ignore rule into the
  workspace's own `.git/info/exclude` (local, uncommitted — never a persistent file left in a
  foreign repo) whenever `runs_dir` is nested under `workspace` and `workspace` is a git worktree.
  No-op under the cross-repository shape (D026), where the ledger already lives outside the tree
  the gate inspects.
- `take_turn` calls it once, at the top, before `runs.open_run` — guaranteed before any transcript
  this turn's executor writes can land.
- Idempotent: the pattern is written once regardless of how many turns call it.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `turn-cycle`: adds a requirement that a turn's own raw transcript never counts as the workspace's
  uncommitted work, under `Places.local`.

## Impact

- `src/yosefactory/runtime/runs.py` — new function.
- `src/yosefactory/runtime/turn.py` — one call in `take_turn`.
- Tests: `tests/runtime/test_runs.py` (unit), `tests/runtime/test_turn_cycle.py` (end-to-end
  regression against `Places.local`, shown to fail before this change and pass after).
- No change to `verify.tree_clean` itself, and no change to what it counts as dirt — untracked
  files still fail the gate, which is the property `tree_clean` exists to enforce. Only the one
  category of untracked file the platform itself produces is now guarded.

## Non-goals

- Not fixing the CI/cross-repo shape (D026) — it cannot hit this defect; a CI-only receipt would
  not be a real fix, so this change is verified against `Places.local` specifically.
- Not moving the ledger itself, and not changing where transcripts are written
  (`executor/claude.py`'s `runs_dir / f"{run_id}.stream.jsonl"` is unchanged).
- Not relaxing `verify.tree_clean` to ignore untracked files generally — that would let an agent
  pass the gate having written nothing tracked at all, the exact failure `tree_clean` exists to
  catch (named explicitly in S237 as the wrong fix).
- Not committing an ignore rule into any foreign workspace's tracked `.gitignore` — this platform
  has no standing to leave persistent files in a repo it does not own.
