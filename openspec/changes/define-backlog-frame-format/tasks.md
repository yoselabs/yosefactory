## 1. The acceptance test first

- [x] 1.1 Write `backlog/fixtures/falsified-round-trip/` by hand: the falsified item's log and its successor's log, as literal `.jsonl` lines, before any code exists to read them
- [x] 1.2 Write `tests/protocol/test_backlog_round_trip.py` against those fixtures, asserting the spec's round-trip scenario — falsified item reads `falsified` with its full frame and trail and `successor`; successor reads `ready` with `predecessor` and the falsification in its frame; following the link forward and back returns to the start; nothing present before the falsification is absent after
- [x] 1.3 Confirm the test fails for the right reason (no module), not the wrong one (bad fixture path)

## 2. The generic fold

- [x] 2.1 `src/yosefactory/protocol/eventlog.py`: parse a `.jsonl` log, one JSON object per line, rejecting a malformed line or a missing `event_id`/`ts`/`actor`/`event` with the file and line number
- [x] 2.2 Order by `ts`, tie-break on `event_id`; dedup on `event_id`
- [x] 2.3 Apply a declared transition table: unknown event and illegal from-state both fail the read, naming what was found and what was expected
- [x] 2.4 `terminal()` over a declared terminal set; no state named `terminal`
- [x] 2.5 No item-specific logic anywhere in this module — a reviewer should not be able to tell from it that backlog items exist

## 3. The item declaration

- [x] 3.1 `src/yosefactory/protocol/backlog.py`: the thirteen states, the terminal set, and the event table from the spec, as data the fold consumes
- [x] 3.2 Frame validation: `created` carries `goal`, `method`, `assumptions`; `frame_amended` carries only changed keys; current frame is the fold of both
- [x] 3.3 `awaiting` validation: `deadline` and `on_timeout` required, `on_timeout` one of `escalate` / `default:<answer>` / `abandon:<reason>`; a block missing either fails the read
- [x] 3.4 `unblocked` returns the item to the `return_to` stored on the `blocked` event it resolves, for both an answer and a timeout
- [x] 3.5 Make the tests from group 1 pass

## 4. Cover the rest of the spec's scenarios

- [x] 4.1 Merge-order test: the same lines in two different file orders fold to the same state
- [x] 4.2 Duplicate-line test: the same `event_id` twice applies once
- [x] 4.3 Unknown-event test: an event outside the table fails the read rather than being skipped
- [x] 4.4 Post-terminal test: an event appended after a terminal state is rejected, `note` excepted
- [x] 4.5 Failure-is-not-falsification test: an infrastructure error records `failed` and emits no successor
- [x] 4.6 Duplicate/survivor test: closing a duplicate writes no line to the survivor's log

## 5. The directory

- [x] 5.1 `backlog/README.md`: the append-only rule, the pointer to this capability's spec, and the one sentence that matters — the state is the fold, never a rewritten field
- [x] 5.2 `backlog/.gitattributes`: `*.jsonl merge=union`, with the reason it is only safe alongside order-insensitive deduplicating reads
- [x] 5.3 `backlog/items/.gitkeep` so the directory exists empty

## 6. Close

- [x] 6.1 `make check` green — lint, types, tests
- [x] 6.2 Commit with explicit pathspecs only, citing D019, D020, D002 and architecture.md §3/§4/§5; `PREK_ALLOW_NO_CONFIG=1`
- [ ] 6.3 Report to the director: what the build taught, and anything in the fold's shape that constrains what a question can declare
