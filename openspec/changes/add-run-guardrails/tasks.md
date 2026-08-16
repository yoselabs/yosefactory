## 1. Protocol — the frozen surface

- [ ] 1.1 Add `Outcome` enum to `protocol/` with exactly `advanced | blocked | nothing-ready | failed`, and a test that a fifth value cannot be constructed
- [ ] 1.2 Add `TurnRecord` type to `protocol/` carrying `run_id`, `started_at`, `ended_at`, `outcome`, `enforced_by` (`agent | harness`), `dirty`, `isolated`, plus free-form `note`
- [ ] 1.3 Validation: reject a record with a missing, empty, or unknown `outcome`; reject a missing `enforced_by`, `dirty`, or `isolated`
- [ ] 1.4 Validation: reject any field value containing an absolute home-directory path, so a public-repo leak fails at write time rather than at review time
- [ ] 1.5 Add the I9 predicate signature to `protocol/` — the type that says a `done` transition requires a passed independent check. Signature only; the checks live in runtime
- [ ] 1.6 Confirm nothing else was added to `protocol/` (D3): the module holds an enum, a record type, and one predicate signature

## 2. The record stream

- [ ] 2.1 Writer for `ledger/runs/<utc-ts>-<run-id>.toml`, one file per record, refusing to overwrite an existing file
- [ ] 2.2 Start-marker writer (`.start`) and the supersede rule: a terminal record satisfies its marker (D2)
- [ ] 2.3 Reader returning the last N records in order, treating an orphan `.start` as a `failed` position rather than skipping it
- [ ] 2.4 Test: the three pre-existing `ledger/*.toml` rows are never read, matched, or touched by any of the above — verified by the reader's scope, not by a skip-list
- [ ] 2.5 Test: two writers finishing simultaneously produce two files and no lost record

## 3. Stall detection

- [ ] 3.1 Detector over the last N records: fires when none carries `advanced`
- [ ] 3.2 Test: a window of all `nothing-ready` fires; a window of all `blocked` fires; a window mixing `failed` and `nothing-ready` fires
- [ ] 3.3 Test: one `advanced` anywhere in the window clears it
- [ ] 3.4 Test: an empty stream and a window of nothing but orphan markers both fire, rather than reporting no data
- [ ] 3.5 Alarm output states window size, outcome counts, and the age of the last `advanced` (or that there is none)
- [ ] 3.6 Non-zero exit on fire, invocable with no run in progress
- [ ] 3.7 Grep the tree for any place `nothing-ready` could be counted as success; add a test asserting the prohibition holds

## 4. Verification gate (I9)

- [ ] 4.1 Independent checks: test suite passes, claimed commit present in history, working tree clean — each evaluated separately
- [ ] 4.2 A run producing no terminal structured verdict fails, even on exit status zero
- [ ] 4.3 `done` is writable only behind a passed gate; no path exists that writes it from a self-report
- [ ] 4.4 Failure output names which check failed and what it observed
- [ ] 4.5 **Acceptance test for the whole change**: a run claiming a commit that does not exist FAILS rather than reporting success
- [ ] 4.6 Test: a run claiming success with a dirty tree fails; a run claiming success with failing tests fails

## 5. Run supervision

- [ ] 5.1 Wall-clock deadline: SIGTERM, grace window, SIGKILL (D5)
- [ ] 5.2 Turn ceiling; refuse to start a run with no ceiling configured
- [ ] 5.3 On termination, supervisor writes the record itself: `outcome: failed`, `enforced_by: harness`, `dirty` computed after the process is gone
- [ ] 5.4 If the agent flushes its own verdict inside the grace window, the record is `enforced_by: agent` instead
- [ ] 5.5 Single-flight via non-blocking `flock`; a second run exits immediately without work; the lock releases on termination
- [ ] 5.6 Tests against real short-lived subprocesses: one that overruns, one that exits non-zero, one that writes no record, one that leaves the tree dirty
- [ ] 5.7 Assert the supervisor requires no resident process between runs

## 6. Isolation policy

- [ ] 6.1 Typed policy, default isolated; opting out is explicit and cannot be reached by omission or a missing config file
- [ ] 6.2 Policy never selects bare mode, in either posture (the subscription-auth trap)
- [ ] 6.3 Preflight asserting a clean `$HOME`, returning a boolean plus a reason code (`clean | user-config-present | home-unset`)
- [ ] 6.4 Test: preflight output contains no absolute path in either result
- [ ] 6.5 Test: resolving a policy and running the preflight spawns no executor — this capability stops at policy
- [ ] 6.6 The resolved posture is recorded on the turn record
- [ ] 6.7 Preflight asserts the session cannot be suspended by an approval prompt — a prompt must fail and return a denial, not wait. Measured true on this fleet today; the assertion is what stops a mode change reopening it silently

## 7. Configuration

- [ ] 7.1 `[tool.yosefactory.guardrails]` in `pyproject.toml`: window size N, wall-clock seconds, turn ceiling, grace window
- [ ] 7.2 Defaults ship with a comment marking N and the wall clock as guesses pending traffic; wall clock well under six hours
- [ ] 7.3 Test: no config surface accepts or stores a token, credential, or home path

## 8. Close

- [ ] 8.1 `make check` green — ruff, ty, pytest
- [ ] 8.2 Ledger row appended for this session, in the existing `ledger/` format
- [ ] 8.3 Commit with an explicit pathspec listing only this change's files (never `git add .`, never a directory), `PREK_ALLOW_NO_CONFIG=1`, citing D021 / I9 / D002
- [ ] 8.4 Report to the visionary session: what shipped, what the three uncalled guards still owe, and the debt's named owner
- [ ] 8.5 Write-back check: did anything here contradict a P160 entity? If yes, capture against the id before closing; if no, say so explicitly rather than staying silent
