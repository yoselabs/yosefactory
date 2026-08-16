## 1. Fixtures

- [x] 1.1 `queue` and `workspace` git fixtures (separate repos, each `git init` + seeded commit +
      `user.name`/`user.email` configured so an agent commit in `workspace` needs no config of its own)
- [x] 1.2 `queue`'s `backlog/items/` and `questions/` directories present, matching `Places` layout
- [x] 1.3 Skip guard identical to `tests/executor/test_integration.py` (absent `claude`, or version
      != `PINNED_VERSION`)

## 2. The real executor wrapper

- [x] 2.1 `IsolationPolicy(isolated=False, workspace_scoped=True, allowed_tools=("Bash", "Write",
      "Edit", "Read"), opt_out_reason=...)` module-level constant (`Read` added after a real run showed
      its omission denied the skill-file read — see design.md)
- [x] 2.2 Closure matching the `Executor` protocol exactly (positional `frame, workspace, limits`;
      keyword `run_id, runs_dir, invocation`), calling `claude.run(..., policy=POLICY)`, no `recorder`
- [x] 2.3 Frame builder: `goal` = the file ends with `<marker>`, committed; `method` = append then
      `git add`/`git commit`; `assumptions` = git identity already configured. No reporting/proposal
      instructions in the frame — those travel only through `Invocation`/the skill. Unique marker per
      call so two turns' edits are distinguishable.
- [x] 2.4 `skill=` passed as `Path("workflows/turn-skill.md").resolve()` (absolute, readable
      regardless of the workspace cwd) — this is what carries the "write one JSON event" instruction,
      not the frame

## 3. The two-turn scenario (assertions 1-4, narrowed per proposal.md's Finding)

**No longer 3.x: assert `Outcome.ADVANCED`.** The receipt is narrowed to a `FAILED` terminal outcome
that needs no vocabulary taught to the agent — see proposal.md - Finding. `test_command` is dropped:
`verify.may_write_done` is never reached on this path.

- [x] 3.1 Seed one `ready` backlog item in `queue` with the real task frame
- [x] 3.2 Call `take_turn` with `Places(queue=..., ledger=queue/turn.RUNS, queue_lock=...,
      workspace=..., workspace_lock=...)`, real `Guardrails` including `cost_ceiling_usd`
- [x] 3.3 Assert `record.outcome is Outcome.FAILED` (documented: the agent does real work but cannot
      yet name a legal completion event); surface `record.note` on failure for diagnosis
- [x] 3.4 Assert the workspace's git log gained a commit and `notes.txt` contains the marker line
      (proves the agent's real work landed even though `take_turn`'s own record is `FAILED`)
- [x] 3.5 Assert `workspace` has no `backlog/`, `questions/`, `ledger/` directories
- [x] 3.6 Assert `queue/ledger/runs/<slug>.json` exists, and its `run_id` field equals
      `record.run_id` (read the file, not `record`) — true regardless of outcome, since `_finish`
      writes the row unconditionally
- [x] 3.7 Assert `git log -1 --format=%(trailers)` in `queue` contains both
      `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` and `Yosefactory-Run: <run_id>` — true
      regardless of outcome, since `_finish` commits unconditionally
      **(3.1-3.7 written and passed on a real run: $0.18, `Outcome.FAILED` as expected.)**
- [x] 3.8 Seed a second `ready` item with a second unique marker; call `take_turn` again on the same
      `Places` — run for real ($0.20), second turn also `Outcome.FAILED` as expected.
- [x] 3.9 Assert the second turn's `run_id` differs from the first, and the
      `Co-Authored-By: yosefactory ...` trailer line is byte-identical between the two turns' commits
      (`git log -1 --format=%(trailers)` at each commit, compared as strings) — **passed: two
      independent run ids, one byte-identical trailer.** $0.20 + $0.19 = $0.40 for this pair.

## 4. The crash-before-commit scenario (assertion 6)

- [x] 4.1 Separate `Places` on a fresh empty-backlog `queue`, `workspace` set to a path that is a
      regular *file*, not a directory. **Revised from the original plan** (a path that simply did not
      exist): `single_flight`'s `mkdir(parents=True, exist_ok=True)` silently creates a missing
      directory before `Popen` runs, so that version spawned a real `claude` process ($0.53,
      unplanned) instead of failing for free. A file-not-directory makes the `mkdir` itself raise —
      see the test's own docstring and proposal.md - Impact.
- [x] 4.2 Call `take_turn`; assert it raises (`NotADirectoryError` from `single_flight`'s lock
      acquisition, unhandled, before any executor call) — **verified free: 1.16s, no transcript file.**
- [x] 4.3 Assert exactly one `<slug>.start` and zero matching `<slug>.json` under the queue's
      `ledger/runs/`
- [x] 4.4 Assert the `.start` file is present in `git show HEAD --stat` in the queue (committed, not
      just written to the working tree)
- [x] 4.5 Assert `runs.read_window(ledger, N)` reports that slug as a gap (`is_gap is True`,
      `outcome is Outcome.FAILED`)

## 5. Verify

- [x] 5.1 Run the new file directly against the pinned `claude` binary — **every test passed on a real
      run.** No adjustment was made to `take_turn`, `verify.may_write_done`, or any `IsolationPolicy`
      posture to force a pass; the two real surprises hit (the vocabulary gap, the crash-trigger's
      accidental spend) are both recorded as findings, not routed around. Total real spend across
      development and the final passing runs: $1.63 (breakdown in proposal.md - Impact).
- [x] 5.2 `ruff check src/ tests/` and `ty check src/` clean; full suite (269 tests) passes with both
      real-spend integration files excluded from that run to avoid re-triggering paid tests. `make
      check`'s bare `pytest -q` would re-run every real-spend receipt on a machine with the pinned
      binary present — expected behaviour for this repo's existing receipts, not a defect, but not run
      bare here to avoid unbudgeted re-spend.
