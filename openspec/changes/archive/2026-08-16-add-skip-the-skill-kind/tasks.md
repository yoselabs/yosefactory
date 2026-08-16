## 1. The kind

- [x] 1.1 Add `skip-the-skill` to the closed set in the delta spec, keeping the requirement block
      whole so the archive does not lose detail
- [x] 1.2 State that a kind may be system-emitted rather than stage-requested, and why S062's
      constraint makes that need no special machinery
- [x] 1.3 Add the row to `questions/README.md`'s kinds table — eight, blocking-by-failure

## 2. Close out

- [x] 2.1 `openspec validate add-skip-the-skill-kind --strict` passes
- [ ] 2.2 Commit with `git commit -m … -- <paths>`; `git add` first only for untracked files, and
      `git restore --staged <new>` if the commit is rejected
- [ ] 2.3 Archive, folding the delta into `openspec/specs/question-frame/spec.md`
- [ ] 2.4 Report and retire
