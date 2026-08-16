## Why

`.pre-commit-config.yaml` runs `ruff check src/ tests/` with `pass_filenames: false` and
`always_run: true`, so every commit lints the whole repository. In a tree shared by several
workers ([[orchestration.md]] Article III) that makes **any** worker's half-written Python block
**every** other worker's commit, however unrelated — YF-3's markdown-only change was blocked for
an extended stretch by an unsorted import in a file it never touched.

No promotion entity in K covers this; it is a build-time constraint found by YF-3 during a run,
so the record of it belongs in `decisions/` here rather than in P160.

Now, because YF-3's apply is a long stretch of real Python and the fix pays most before that
starts, not after.

## What Changes

- The `ruff` hook lints **the Python files being committed**, not the whole tree:
  `pass_filenames: true`, `always_run: false`, restricted to `src/` and `tests/` Python.
- `--force-exclude` is added so `ruff`'s own exclusions still apply to explicitly-passed paths.
- A commit that touches no Python skips the hook entirely rather than lint-gating on other
  people's work.
- **Unchanged: `ty` and the shelf guard.** Both stay whole-project, deliberately — see Non-goals.

## Capabilities

### New Capabilities
<!-- None. Tooling configuration; no spec-level behavior changes. `skip_specs: true`. -->

### Modified Capabilities
<!-- None. -->

## Non-goals

- **Not narrowing `ty`.** Type checking is whole-program: a change in one file can break another,
  so per-file type checking is unsound and would trade a shared-tree annoyance for missed errors.
  The dispatch said "lint staged files only" and named the lint hook; extending that to the type
  checker would be a scope widening with a correctness cost. If `ty` turns out to block workers in
  practice the same way, that is its own dispatch with its own argument.
- **Not touching the shelf guard.** It answers a repository-wide question ("is a local shelf
  source referenced anywhere") that has no per-file form.
- **Not removing, weakening, or reordering any check.** Only the file set narrows.
- **Not adding hooks, formatters, or CI.**

## Impact

- One file: `.pre-commit-config.yaml`.
- Behavioural consequence worth stating plainly: lint errors in files *not* being committed no
  longer fail the commit. That is the intent, and `make check` remains the whole-tree gate.
