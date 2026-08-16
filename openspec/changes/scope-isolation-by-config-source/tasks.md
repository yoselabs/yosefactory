# Tasks

- [x] 1. Measure whether `--setting-sources` gates host and workspace config independently of each
      other, on memory, skills, MCP, hooks, and env
- [x] 2. Confirm `--safe-mode` overrides `--setting-sources` rather than composing with it
- [x] 3. Measure `--settings` under `--safe-mode` (left unmeasured by isolate-by-safe-mode)
- [x] 4. Identify and record the account-connector MCP residue that `--setting-sources` cannot reach
- [x] 5. Add the `workspace_scoped` posture to `runtime/isolation.py`, mutually exclusive with
      `isolated`
- [x] 6. Widen `isolated`'s construction-time refusal to cover an explicit `--settings` config
- [x] 7. Add `workspace_scope_leaks` (the one surface `workspace_scoped` can assert absent) and
      document the account-connector residue as named, with no code control, in `executor/stream.py`
- [x] 8. Receipt: a `workspace_scoped` run in a hostile fixture repo admits repo `CLAUDE.md` and
      reports no host plugin registration
- [x] 9. Receipt: `isolated + workspace_scoped` and `isolated` + `--settings` are both refused at
      construction (unit-level; matches the existing `mcp_config_path` refusal test's shape)

Tasks 1-4 were the explore + propose dispatch. Tasks 5-9 are this apply dispatch. Archiving is
blocked — see the note below, added after the release to apply.

## Archive blocked on `isolate-by-safe-mode`

This change's spec delta MODIFIES two requirements by the names `isolate-by-safe-mode` itself
introduces (`The isolated posture is a floor and admits no additions`, `Residue is recorded rather
than treated as a breach`) plus adds a new one to the same capability. Those requirement names do not
exist in the currently promoted `openspec/specs/run-guardrails/agent-isolation/spec.md` — that file
still carries the pre-`isolate-by-safe-mode` text (`A preflight asserts a clean home directory`, no
floor/residue requirements at all) because `isolate-by-safe-mode` is marked complete (9/9 tasks,
`openspec validate --strict` passes) but was never archived.

Attempting `openspec archive isolate-by-safe-mode` to clear the prerequisite surfaces a second,
independent defect: its own spec delta's MODIFIED header
(`### Requirement: A preflight asserts the credential store is reachable`) does not match any header
in the promoted spec (which has `### Requirement: A preflight asserts a clean home directory`) —
`openspec archive` requires an exact header match for a MODIFIED block and does not treat it as a
rename. The tool reports `MODIFIED failed for header "..." - not found` and aborts with no files
changed (confirmed: `git status` clean after the attempt).

This is a defect in a change this worker did not author and does not own (Article IV). Reported to
the director rather than fixed here.
