# Tasks — read-the-failure-kind

Sequenced third by the director. **Do not start before release.** YF-4 holds `executor/`
(isolation, then item 1b); YF-6 holds `protocol/turn.py` immediately before this change.

## 0. At release, before any edit

- [ ] 0.1 Re-read `src/yosefactory/protocol/turn.py` from disk. YF-6 lands a `blocked` reason
      axis there first and this session's copy predates it (Article XII).
- [ ] 0.2 Confirm item 1b landed: `grep -n terminal_reason src/yosefactory/executor/stream.py`
      returns a branch, and `error_max_budget_usd` maps to `RunOutcome.BUDGET_EXHAUSTED`. If
      it did not land, proceed anyway — design D5 fixes the failure direction — and say so in
      the completion report rather than waiting.
- [ ] 0.3 `git status --porcelain` clean of others' work in `src/yosefactory/runtime/`.

## 1. The predicate — `protocol/turn.py`

- [ ] 1.1 Add `_STARVATION = frozenset({FailureKind.RATE_LIMIT, FailureKind.BUDGET_EXHAUSTED})`
      and `is_starvation(kind: FailureKind | None) -> bool`, beside `counts_as_progress` (D1).
      Null returns `False` — unattributable is not starvation (D5).
- [ ] 1.2 Docstring carries the `auth`-is-breakage argument. It is the one placement a later
      reader will want to reverse, and the reason must travel with it.
- [ ] 1.3 Test: every `FailureKind` member is in exactly one of starvation or breakage, so a
      tenth value fails a test rather than defaulting into "broken" (D2).
- [ ] 1.4 Test: `is_starvation(None)` is `False`.

## 2. The writer — `runtime/turn.py`

- [ ] 2.1 Add the `RunResult` → `FailureKind | None` mapping (D3): a dict keyed on
      `RunOutcome` for the run-level stops, falling back to the typed executor kind. Explicit
      and total; never `FailureKind(result.outcome.value)` by string coincidence.
- [ ] 2.2 Test: every `RunOutcome` member is handled, including `SUCCESS`, `NEEDS_APPROVAL`
      and `REFUSED` mapping to `None` — a non-`FAILED` outcome may not carry a reason and the
      record rejects one.
- [ ] 2.3 Thread `failure_kind` through `_finish(...)` to the `TurnRecord` constructor. Every
      other `_finish` caller passes nothing and keeps today's null.
- [ ] 2.4 Retire the live workaround at `runtime/turn.py:397`: the f-string stops carrying
      `({result.failure_kind or 'no kind'})`, because the typed field now does.
- [ ] 2.5 Test: an executor result reporting a budget stop produces a record whose
      `failure_kind` is `budget_exhausted` and whose note does not restate it.
- [ ] 2.6 Test: a record written for a non-failing turn carries `failure_kind: None`.

## 3. The harness's own reason — `runtime/supervise.py`

- [ ] 3.1 A turn-ceiling stop records `FailureKind.TURN_LIMIT`. A wall-clock stop records
      `None` and the note names the bound that fired — the union has no value for it and this
      change adds none.
- [ ] 3.2 Test: a ceiling kill carries `turn_limit` **and** `enforced_by: harness`. Both, in
      one assertion — the reason must not silently re-attribute the ending.
- [ ] 3.3 Gate: `tests/runtime/test_supervise.py` passes with only additions. A changed
      existing case means this was not additive; stop and report.

## 4. The reader — `runtime/stall.py`

- [ ] 4.1 `Position` exposes the record's `failure_kind` (null for a gap).
- [ ] 4.2 Replace `Verdict.stalled: bool` with a three-state field (D4). Do not keep the
      boolean alongside it.
- [ ] 4.3 `evaluate` classifies: starved requires no `advanced`, at least one starvation
      position, and no non-starvation position — gaps, `nothing-ready` and `blocked` included.
- [ ] 4.4 `report()` names the classification and the reasons that produced it.
- [ ] 4.5 `main()` returns 0 / 1 broken / 2 starved (D6).
- [ ] 4.6 Tests: a wholly starved window; one crash among starved turns; one gap among starved
      turns; one `nothing-ready` among starved turns; an `advanced` present clears everything.
- [ ] 4.7 Test: a starved window still exits non-zero. This is the requirement most likely to
      be "simplified" later and it needs a test that names why.
- [ ] 4.8 Test: an `auth` window is broken, not starved.

## 5. Deferred — not this change

- [ ] 5.1 Confirm at close that `RunResult.note()` removal is still deferred (its file belongs
      to `implement-claude-executor`). If that change archived while this one ran, report it;
      do not opportunistically take the file (Article VI).

## 6. Close

- [ ] 6.1 `make check` green.
- [ ] 6.2 `openspec validate read-the-failure-kind --strict`.
- [ ] 6.3 Ledger row in `ledger/`, next seq, TOML like its neighbours.
- [ ] 6.4 Commits: explicit literal pathspecs, one idea each, new file and its consumer in the
      same commit.
- [ ] 6.5 Report to the director: whether 1b had landed, and the honest state of the
      distinction if it had not. Supply write-back findings; do not author in P160.
