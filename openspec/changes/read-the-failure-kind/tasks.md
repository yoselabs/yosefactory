# Tasks — read-the-failure-kind

Sequenced third by the director. YF-4 held `executor/` (isolation, then item 1b); YF-6 held
`protocol/turn.py` immediately before this change.

## 0. At release, before any edit

- [x] 0.1 Re-read `src/yosefactory/protocol/turn.py` from disk. Found `blocked_kind`,
      `_check_reason`/`_read_reason`, `resumable()` — none anticipated when this was written.
- [x] 0.2 Confirm item 1b landed. It had: `8069e0f`, `classify` reads `terminal_reason` and the
      `error_max_budget_usd` subtype.
- [x] 0.3 Tree clean of others' work in `src/yosefactory/runtime/`.

## 1. The predicate — `protocol/turn.py`

- [x] 1.1 Added `STARVATION` (frozenset) and `starved(kind) -> bool | None` beside
      `counts_as_progress`, matching the tri-state shape of `resumable()` found at 0.1 rather
      than the boolean this task originally specified — an absent reason is not evidence that a
      failure was not starvation, and `resumable()` already made that argument once.
- [x] 1.2 Docstring carries the `auth`-is-breakage argument.
- [x] 1.3 Test: `STARVATION` and its complement partition every `FailureKind`; a tenth value
      fails the test.
- [x] 1.4 Test: `starved(None) is None` — covers 1.4 under the tri-state signature.

## 2. The writer — `runtime/turn.py`

- [x] 2.1 `_RUN_LEVEL_KIND`, total over `RunOutcome`, asserted by test.
- [x] 2.2 Test: every `RunOutcome` member handled; `SUCCESS`/`NEEDS_APPROVAL`/`REFUSED` → `None`.
- [x] 2.3 Threaded through `_finish` → `TurnRecord`.
- [x] 2.4 F-string at `runtime/turn.py:397` no longer restates the kind.
- [x] 2.5 Test: a budget stop's record carries the typed kind and the note doesn't restate it.
- [x] 2.6 Test: a non-failing turn's record carries `failure_kind: None`.

## 3. The harness's own reason — `runtime/supervise.py`

- [x] 3.1 Ceiling stop → `TURN_LIMIT`. Wall-clock stop → `None`, note names the bound.
- [x] 3.2 Test: ceiling kill carries `turn_limit` and `enforced_by: harness` in one assertion.
- [x] 3.3 Gate held: the diff against the existing suite added tests and one import line; no
      existing case's body changed.

## 4. The reader — `runtime/stall.py`

- [x] 4.1 `starved()` reads `Position.record.failure_kind` directly; no new field needed.
- [x] 4.2 `Verdict.stalled: bool` replaced by `status: Status` (OK/STALLED/STARVED) as the one
      stored field. **Deviation, disclosed:** `stalled` survives as a read-only `@property`
      derived from `status`, kept so the seven pre-existing tests asserting `verdict.stalled`
      needed no rewrite. It cannot drift from `status` — there is nothing to keep in sync — so
      it does not reintroduce the two-fields hazard D4 was written against; a stored second
      field would have.
- [x] 4.3 `evaluate` classifies as specified; a null-reason failure and a gap both fail to
      classify as starvation.
- [x] 4.4 `report()` names the classification and the reason counts.
- [x] 4.5 `main()`: 0 / 1 / 2.
- [x] 4.6 All five window compositions tested, plus `advanced` clearing a starved-looking window.
- [x] 4.7 Test: starvation still exits non-zero, and a second test asserts the two alarm codes
      are distinct from each other.
- [x] 4.8 Test: an `auth`-only window is broken.

## 5. Deferred — not this change

- [x] 5.1 Re-confirmed at close: `RunResult.note()` has no production caller, one test
      reference, unchanged. `implement-claude-executor` archived mid-run (`432d442`); a
      **new** change, `write-the-reason-fields`, now owns `executor/` (0/25 tasks at last
      check) — not taken opportunistically (Article VI); reported to the director instead.

## 6. Close

- [x] 6.1 `make check` equivalent green: ruff, ty, pytest — 235 passed, tree-wide.
- [ ] 6.2 `openspec validate read-the-failure-kind --strict` — pending final artifact sync.
- [ ] 6.3 Ledger row.
- [x] 6.4 Four commits, explicit literal pathspecs, one idea each: `f9d79b0` (predicate),
      `73738cf` (writer), `b2757b3` (supervisor reason), `8a02a46` (reader).
- [ ] 6.5 Report to the director — next.
