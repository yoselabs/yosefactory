## 1. Baseline

- [x] 1.1 Record the measured baseline before any edit: `make check` counts, and `git status --porcelain` so another worker's dirty file is attributable to them and not to this change (S184, S191)
- [x] 1.2 Confirm `protocol/turn.py` and `tests/protocol/test_turn.py` are clean in the shared tree before touching them (Article XII — verify, do not trust a report)

## 2. The field

- [x] 2.1 Add `BlockedKind` to `src/yosefactory/protocol/turn.py` with `awaiting`, `needs_approval`, `refused`, and a docstring stating the two-axes argument and which values are dead ends
- [x] 2.2 Add `blocked_kind: BlockedKind | None = None` to `TurnRecord`, after `failure_kind`, with the comment naming what null means
- [x] 2.3 Reject a non-`BlockedKind` value, and reject any `blocked_kind` on an outcome other than `blocked`, with a message naming both fields — same wording shape as the `failure_kind` check
- [x] 2.4 Serialise it in `to_dict` and accept it in `from_dict`: a missing key is null, an unknown value is a `RecordError` naming the value and the valid set

## 3. Resumability, derived once

- [x] 3.1 Add `RESUMABLE: frozenset` naming the kinds a block can clear from on its own, and a `resumable(kind) -> bool | None` returning `None` for a null kind
- [x] 3.2 Update the module docstring so the two-axes paragraph covers both reason fields and states the D4 unification trigger

## 4. Tests

- [x] 4.1 A wait is distinguishable from a dead end: two records, both `blocked`, separated by kind alone
- [x] 4.2 A `blocked_kind` on `advanced` is rejected, and the error names both fields
- [x] 4.3 An unknown `blocked_kind` in a payload is rejected by `from_dict`
- [x] 4.4 A payload with no `blocked_kind` key reads back with null and unknown resumability
- [x] 4.5 Round-trip through `to_dict`/`from_dict` preserves the kind
- [x] 4.6 `resumable` returns `None` for a null kind, `False` for `refused`, `True` for the other two
- [x] 4.7 Drift detector: every `RunOutcome` narrowing to `Outcome.BLOCKED` has a `BlockedKind` of the same name — read-only import of `executor.outcome`, as in the `failure_kind` detector
- [x] 4.8 A record cannot carry both reason fields, because it cannot carry both outcomes

## 5. Spec

- [x] 5.1 `openspec validate --strict distinguish-resumable-blocks` passes — the delta is ADDED only, so no existing requirement block needs reproducing
- [x] 5.2 Confirm no other spec in `run-guardrails/` claims `blocked` carries no reason; fix only where this change makes an existing statement false

## 6. Close

- [x] 6.1 `make check` green, compared against the 1.1 baseline; a rejection naming a file this change did not touch is reported as S191, not debugged
- [x] 6.2 One commit, explicit literal pathspecs, `PREK_ALLOW_NO_CONFIG=1`; new files staged in the same command as the commit and unstaged explicitly if it is rejected (Article V)
- [x] 6.3 Archive with `openspec archive distinguish-resumable-blocks` and promote the delta into `openspec/specs/run-guardrails/turn-record/spec.md`
- [x] 6.4 Report to the director: the two mapping sites left unpopulated, the unconsumed `absorbed()` finding, and anything the build taught that contradicts this design

## Outcome

**Landed** as `ee2bd92`: `BlockedKind`, the field, `RESUMABLE` + `resumable()`, and 11 tests.
Baseline `make check` was 196 passed at `ead5d25`; after this change, 211. Four of the fifteen are
not mine — `8069e0f` and `5857320` landed while this was being written, verified by `git log` rather
than assumed.

**What the build taught, none of it contradicting the design:**

- **Two reason fields made the validation duplicate before the third arrived.** The `failure_kind`
  check was four lines of enum-and-outcome validation; writing the second one verbatim was the moment
  to extract `_check_reason`/`_read_reason` instead. So the D4 rule-of-three trigger applies to the
  *fields*, and the duplication it was guarding against showed up in the *checks* at two, not three.
  Extracted rather than repeated; the fields stay separate as ratified.
- **The drift detector reads the mapping, not a hand-copied set.** Task 4.7 said "of the same name",
  which would have been a literal list to keep in step. `executor.outcome._TO_PROTOCOL` is the actual
  narrowing, so the test derives the blocking outcomes from it and asserts the pair — a new
  `RunOutcome` narrowing to `blocked` breaks it without anyone remembering to edit a list.
- **Task 5.2 found nothing to fix.** `run-guardrails/stall-detection` already treats `blocked` as a
  stall input and stays true under this change; it is the consumer that will read the field, not a
  statement this change falsified.

**Left, deliberately, and each belongs to someone else:**

- `executor/outcome.py` and `executor/stream.py` — the two sites that would populate the field.
  Until that dispatch, `blocked_kind` is null on every real row. Same interim `failure_kind` spent.
- `RunResult.note()`'s free-text workaround, retirable now both typed fields exist.
- Bounding `needs_approval` with a question so it acquires a deadline — `runtime/`, and the S172
  violation it would close is declared in the spec meanwhile.
- A consumer for `question.absorbed()`, which retains evidence nothing reads.
