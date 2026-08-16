## 1. Compose the message

- [x] 1.1 Add a frozen module-level constant for the co-author identity and the run-trailer key in `src/yosefactory/runtime/turn.py`, with a comment stating that changing either splits one author into two in history that cannot be corrected.
- [x] 1.2 Add a function that takes a message and a run id and returns the message with both trailers appended, delegating to `git interpret-trailers --trailer <k>=<v>` (message on stdin, amended message on stdout) so existing trailers are preserved by the tool rather than by hand.
- [x] 1.3 Raise `TurnError` if `interpret-trailers` fails, and do not fall back to string concatenation. An unmarked commit enters the record as hand-driven work and cannot be corrected afterwards.

## 2. Bind it to the only writer

- [x] 2.1 Give `commit()` a required keyword-only `run_id`, and compose the message through 1.2 before invoking `git commit`. Leave the explicit-pathspec handling and the `git restore --staged` failure path untouched.
- [x] 2.2 Pass `run_id` at every call site: the run-marker declaration and the claim in `take_turn`, and the disposition commit in `_finish`. Confirm by search that no other call site exists.

## 3. Receipts

- [x] 3.1 Test that a commit produced by a turn carries both trailers, read back with `git log --format=%(trailers)` rather than by string-matching the message.
- [x] 3.2 Test that the `Yosefactory-Run` value equals the run id the turn record is keyed by, and that the record file named by it exists — the trail is asserted end to end, not per-field.
- [x] 3.3 Test that a message already carrying a `Co-Authored-By` keeps it and gains the platform's, and that the subject and body are unchanged.
- [x] 3.4 Test that the co-author identity is byte-identical across two commits from two different runs.
- [x] 3.5 Test that a commit refused by the gate still leaves nothing staged, using the existing failure-path test as the model — the trailer must not have changed that behaviour.
- [x] 3.6 Confirm no fixture, skill file, frame, or prompt anywhere mentions a trailer, so the marker cannot be satisfied by an agent's cooperation.
- [x] 3.7 Test that a message already ending in a trailer block gains the platform's trailers inside that block, with no second block and no stray blank line.
- [x] 3.8 Verify the stated git dependency holds on this machine (`interpret-trailers --trailer` present) and record the observed version in the apply report.

## 4. Close

- [x] 4.1 `tests/runtime/test_turn_cycle.py` green (42/42) with no pre-existing assertion weakened; full suite green (255/255). Whole-repo `make check` not run as a gate on this change — a repo-wide result is not a statement about these two files (S184: another worker's dirty file elsewhere fails it regardless of this change). `ruff check` and `ty check` scoped to `src/yosefactory/runtime/turn.py` and `tests/runtime/test_turn_cycle.py`: clean.
- [x] 4.2 Commit with explicit literal pathspecs only, `PREK_ALLOW_NO_CONFIG=1`, `git restore --staged -- <literal paths>` on failure.
- [x] 4.3 Report to the director: whether the first real `git interpret-trailers` call behaved as the design assumed, and anything the tests could not reach because `take_turn` has still never run against a live repository.
