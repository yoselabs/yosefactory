## 1. Narrow the lint hook

- [x] 1.1 In `.pre-commit-config.yaml`, change the `ruff` hook to `pass_filenames: true`,
      `always_run: false`, `files: ^(src|tests)/.*\.py$`, entry `uv run ruff check --force-exclude`
- [x] 1.2 Leave `ty` and the shelf guard exactly as they are, and record why in the proposal's
      Non-goals rather than silently widening the change

## 2. Verify by construction

- [x] 2.1 Confirm the hook now receives filenames: a markdown-only commit skips `ruff` instead of
      linting the tree
- [x] 2.2 Confirm a Python commit still lints the Python it commits
- [x] 2.3 Confirm `make check` still lints the whole tree, so nothing is lost — only the commit
      gate narrows

## 3. Close out

- [x] 3.1 Record the constraint and the fix in `decisions/` — a build-time ADR, not a P160 entity
- [ ] 3.2 Commit by passing pathspecs directly to `git commit` (no staging step), citing YF-3 as
      the finder
- [ ] 3.3 Report to the director, including the `ty` reasoning, since that is the part of the
      dispatch I deliberately did not do
