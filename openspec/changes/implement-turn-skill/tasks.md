## 1. The appender, which everything else depends on

- [x] 1.1 Write the event appender in `runtime/turn.py`: read the item log, build the candidate line
      with a turn-generated `event_id` (UUID4) and `ts` (RFC3339 UTC), write log-plus-candidate to a
      temporary file, fold it through `protocol.backlog.ITEM`, and rename over the item log only on
      success
- [x] 1.2 Test: a legal event is appended and the fold reports the expected new state
- [x] 1.3 Test: an illegal transition leaves the item log byte-for-byte unchanged and raises
- [x] 1.4 Test: a missing required field leaves the log unchanged and raises
- [x] 1.5 Test: creating the first item writes a well-formed `created` log that folds to `ready`

## 2. Acquire and classify — the deterministic pre-check

- [x] 2.1 Load every item under `backlog/items/*.jsonl` and fold each one
- [x] 2.2 Apply answers: for each item blocked on a question that has since closed, append
      `unblocked` carrying the resolution, letting the fold read the target from `awaiting.return_to`
- [x] 2.3 Classify from state alone — plan when nothing is eligible, act otherwise — and refuse any
      argument that names a phase
- [x] 2.4 Pick exactly one eligible item, deterministically (priority, then id)
- [x] 2.5 Test: an empty backlog classifies as planning
- [x] 2.6 Test: a ready item classifies as acting and exactly one item is selected
- [x] 2.7 Test: an answered question unblocks its item in the same turn that finds the answer
- [x] 2.8 Test: an open question leaves its item ineligible
- [x] 2.9 Test: a phase-naming argument is refused before any agent could run

## 3. The nothing-ready path — the turn that costs nothing

- [x] 3.1 On nothing eligible: write a `nothing-ready` turn record via `runs.open_run` and
      `runs.append`, commit it by explicit pathspec, and exit without invoking the executor
- [x] 3.2 Create `ledger/runs/` on first write
- [x] 3.3 Test: no executor call is made (the fake executor records that it was never invoked)
- [x] 3.4 Test: exactly one record is written and its outcome is `nothing-ready`

## 4. The executor seam and the proposal channel

- [x] 4.1 Define the executor as a typed protocol matching
      `run(frame, workspace, limits) -> RunResult`, injected by the caller, with no default binding
      to a module that does not yet exist
- [x] 4.2 Build the frame the agent receives: the item's frame (goal, method, assumptions), the
      proposal path, and the skill to run
- [x] 4.3 Allocate the proposal path outside the repository so a killed run cannot dirty the tree
- [x] 4.4 Read and parse the proposal: exactly one JSON object; more than one event, a missing file,
      or unparseable content is a refusal
- [x] 4.5 Reject any agent-supplied `event_id` or `ts`
- [x] 4.6 Write the fake executor for tests — returns a scripted proposal, records its invocations
- [x] 4.7 Test: a proposal carrying two events is refused and nothing is written
- [x] 4.8 Test: a missing proposal file yields `failed`, not silence
- [x] 4.9 Test: a proposal that is not a JSON object yields `failed`

## 5. Claim, act, record — the acting turn

- [x] 5.1 Append `claimed` with `owner`, `expires_at` and `attempt`, and commit it by explicit
      pathspec before the executor is invoked
- [x] 5.2 Append `started`, invoke the executor, and read the proposal
- [x] 5.3 Route a proposed `done` through `verify.may_write_done` and write it only if the gate
      passes; on failure write no event and record `failed` carrying what the gate observed
- [x] 5.4 Append the accepted event and map the result to a turn outcome per design.md
- [x] 5.5 Write the turn record, naming the item in `note`, with `enforced_by` reflecting whether the
      agent or the turn authored the verdict
- [x] 5.6 Commit the outcome event and the record together, by explicit pathspec
- [x] 5.7 Test: the claim is committed before the executor is invoked (ordering asserted, not assumed)
- [x] 5.8 Test: a proposed `done` with a failing gate writes no `done` event and records `failed`
- [x] 5.9 Test: a proposed `done` with a passing gate records `advanced`
- [x] 5.10 Test: a proposed `blocked` records `blocked`, and the item is blocked with its `awaiting`
      block intact

## 6. The planning turn

- [x] 6.1 Allocate item ids as `itm-<YYYYMMDD>T<HHMMSS>Z-<8 hex>`, generated without reading the
      backlog — no scan, no counter (S186)
- [x] 6.2 Write one `created` log per planned item, each carrying `loop` and a full frame
- [x] 6.3 Record `advanced` and commit the new item logs and the record by explicit pathspec
- [x] 6.4 Test: a planning turn against an empty backlog writes exactly the items proposed and does
      not act on them

## 7. Concurrency posture

- [x] 7.1 Hold `supervise.single_flight` for the whole turn
- [x] 7.2 Refuse to run when configured for cross-machine operation without the CAS push, naming the
      missing protection
- [x] 7.3 Test: a second turn against a locked tree does not start and says why
- [x] 7.4 Test: cross-machine configuration without the push is refused

## 8. The skill file

- [x] 8.1 Write the skill: where to write, what shape, one event only — no restatement of the
      transition table or the required fields
- [x] 8.2 Test: the skill's word count stays under the bound

## 9. Close

- [x] 9.1 `make check` green — ruff, ty, pytest
- [x] 9.2 Two-turn acceptance test with the fake executor: turn one plans one item from an empty
      backlog and commits; turn two, as a fresh call sharing nothing but the repository, claims and
      acts on it
- [ ] 9.3 Report to the director what building taught, including whether the executor seam carried
      the frame a turn needs
- [ ] 9.4 Write back to P160 against the entity ids this change refuted or confirmed, per
      `build-loop.md`, and cite the ids in the commit message
