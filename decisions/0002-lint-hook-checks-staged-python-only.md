# ADR-0002 — The lint hook checks staged Python only

**Status:** Accepted
**Date:** 2026-08-16
**Supersedes:** —
**Superseded by:** —

## Context

Several workers share one working tree and one git index (`orchestration.md` Article III). The
`ruff` hook ran `uv run ruff check src/ tests/` with `pass_filenames: false, always_run: true`, so
every commit linted the whole repository — including files belonging to other workers, in whatever
state those workers had left them mid-edit.

The failure is not hypothetical. YF-3 was blocked from committing a markdown-only change for an
extended stretch by an unsorted import in a half-written file it had never opened. It correctly
declined to fix a shared config file unilaterally and reported instead; the fix was then
dispatched.

The general shape: a repository-wide pre-commit gate assumes one author at a time. That assumption
is false here, and the cost lands on whoever commits next rather than on whoever wrote the error.

## Decision

The `ruff` hook lints the Python files being committed:

```yaml
- id: ruff
  name: ruff check (staged python)
  entry: uv run ruff check --force-exclude
  language: system
  files: ^(src|tests)/.*\.py$
  pass_filenames: true
  always_run: false
```

`--force-exclude` keeps `ruff`'s own exclusions honoured when paths are passed explicitly. A commit
touching no Python skips the hook rather than gating on unrelated work.

**`ty` and the shelf guard are deliberately left whole-project.** Type checking is whole-program —
a change in one file can break another — so narrowing `ty` to changed files would trade a
shared-tree annoyance for missed errors, which is a worse bargain than the one being fixed. The
shelf guard answers a repository-wide question that has no per-file form. If either turns out to
block workers the way `ruff` did, that is its own decision with its own argument.

## Consequences

- A lint error in a file that is not part of the commit no longer fails the commit. Intended: the
  commit gate now matches the commit's blast radius.
- **`make check` remains the whole-tree gate**, unchanged, and is what CI and session close run.
  Nothing is unchecked; the check simply happens where it is actionable.
- The residual: a file can be committed by worker A while worker B's unrelated lint error sits in
  the tree unnoticed until `make check`. That is the intended trade, and it is visible rather than
  silent.

## Verification

- `prek run --files questions/README.md` → `ruff … (no files to check) Skipped`; `ty` and the guard
  still run.
- `prek run --files <a deliberately dirty python file>` → three errors reported, hook fails.
- `make check` → ruff and ty clean over the tree, 30 tests pass.

## Trail

- 2026-08-16 — constraint found by YF-3 during its apply, reported rather than worked around;
  dispatched to YF-2 and applied. Recorded here rather than in P160 because it is a fact about how
  this repository is built, not about what the platform should be.
