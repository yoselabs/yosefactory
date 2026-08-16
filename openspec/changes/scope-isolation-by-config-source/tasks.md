# Tasks

- [x] 1. Measure whether `--setting-sources` gates host and workspace config independently of each
      other, on memory, skills, MCP, hooks, and env
- [x] 2. Confirm `--safe-mode` overrides `--setting-sources` rather than composing with it
- [x] 3. Measure `--settings` under `--safe-mode` (left unmeasured by isolate-by-safe-mode)
- [x] 4. Identify and record the account-connector MCP residue that `--setting-sources` cannot reach
- [ ] 5. Add the `workspace_scoped` posture to `runtime/isolation.py`, mutually exclusive with
      `isolated`
- [ ] 6. Widen `isolated`'s construction-time refusal to cover an explicit `--settings` env entry
- [ ] 7. Add the account-connector residue class to `executor/stream.py`'s `init.residue`
- [ ] 8. Receipt: a `workspace_scoped` run in a hostile fixture repo admits workspace config and
      excludes host config, verified from init + a canary turn
- [ ] 9. Receipt: `isolated + workspace_scoped` and `isolated` + `--settings` env are both refused at
      construction

Tasks 1-4 are this dispatch (explore + propose). Tasks 5-9 are implementation, held for the
director's release before `apply`.
