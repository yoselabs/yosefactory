# Design — read-the-failure-kind

## Context

See `proposal.md` — Why. The state that shapes the approach: `failure_kind` validates and
round-trips but has no writer, and `classify` returns `TASK_ERROR` for a budget stop, so the
distinction is destroyed one layer below where this change operates. Item 1b — teaching
`classify` to read `terminal_reason` — is owned by whoever holds `executor/`, and the
director's sequencing lands it before this change. **This design assumes `classify` returns
the true value by the time the mapping is written, and D5 covers the case where it does not.**

## Goals / Non-Goals

Design-level only; the proposal holds the scope.

**Goals.** One place where starvation is defined. A mapping that is total over the executor's
vocabulary and fails visibly when that vocabulary grows. A verdict whose three states are
readable by a scheduler without parsing prose.

**Non-goals.** No lookup table that silently absorbs unknown values. No change to the
`Outcome` narrowing (`_TO_PROTOCOL`) — this change adds a second, parallel mapping and does
not touch the first.

## Decisions

**D1 — The starvation predicate lives in `protocol/turn.py`, beside `counts_as_progress`.**
Not in `stall.py` where it is consumed. Same argument the existing predicate is built on: the
classification is a property of the vocabulary, not of the reader, and a second reader
(`verify`, a future report) must not be able to disagree about what starvation means.
*Alternative rejected:* a `starved` boolean on `FailureKind` members. StrEnum members do not
carry attributes without a metaclass, and the predicate is one frozenset.

**D2 — A frozenset, not an if-chain, and it is closed against the enum.** `_STARVATION =
frozenset({RATE_LIMIT, BUDGET_EXHAUSTED})`. A test asserts every `FailureKind` member is in
exactly one of starvation or breakage, so adding a tenth value fails a test rather than
defaulting silently into "broken". *Why this matters here specifically:* silent default into
breakage is the safe direction for alarms and the wrong direction for evidence — it would
manufacture agreement between a new value and an old classification.

**D3 — The mapping from `RunResult` to `failure_kind` is explicit and total.** Two sources
join: the executor's typed `FailureKind` (six values, same spellings) and the run-level
`RunOutcome` stops (`BUDGET_EXHAUSTED`, `TURN_LIMIT`, `CANCELLED`). The union's names are
disjoint by construction, so the join is unambiguous. Written as a dict keyed on
`RunOutcome` with a fallback to the typed kind, and a test asserting every `RunOutcome`
member is handled. *Alternative rejected:* `FailureKind(result.outcome.value)` by string
coincidence — it works today and breaks silently the first time the two vocabularies diverge,
which is exactly what `outcome.py` says is expected to happen.

**D4 — `Verdict.stalled: bool` becomes a three-state field, and the boolean does not stay.**
Keeping `stalled` alongside a new `starved` invites a reader to check one and not the other,
and the whole change exists because a field nobody read was as good as absent. One field,
three values, and `report()` names it. *Cost, accepted:* `main()`'s exit mapping and every
existing test that asserts `verdict.stalled` change. That is the surface area of the change
being visible, which is preferable to it being invisible.

**D5 — The classification reads the record, and treats null as unattributable.** A failed
position with a null reason is not starvation (spec: "a gap is never starvation" generalises
— null is the same evidentiary state). This is what makes the change safe to land before or
after 1b: with 1b absent, a budget stop arrives as `task_error` and is classified **broken**,
which is wrong but loud. With 1b present it is classified starved. **At no point does a
missing or wrong reason produce silence.** The failure direction is fixed by construction
rather than by sequencing.

**D6 — Exit statuses: 0 ok, 1 broken, 2 starved.** 1 stays on the existing stall so a
scheduler configured against today's detector keeps working and gets *more* specific, never
less. The new state takes the new number. *Alternative rejected:* 2 for broken, on the
argument that broken is more severe — it would silently redefine what an existing 1 means.

## Risks / Trade-offs

- **1b does not land, or lands after this.** → D5 fixes the failure direction: a budget stop
  reads broken, which over-alarms and never under-alarms. Named in the proposal as the honest
  description of this change shipping alone.
- **`protocol/turn.py` is edited by another worker in the same pass** (the director's ordering
  puts YF-6 there immediately before this change, adding a `blocked` reason axis). → Re-read
  the file at release rather than trusting this session's copy (Article XII); the predicate is
  additive and does not touch what that change adds.
- **Three states where a scheduler expects two.** → Both alarm states are non-zero, so any
  existing `if exit != 0` caller keeps alarming; only a caller that tests `== 1` needs to
  know, and there is none in the repository.
- **The window still is not a neutral instrument.** → Not mitigated. Owned by name in the
  proposal; naming the verdict starved makes it legible without making it false.

## Migration Plan

No migration. Records on disk carry null and stay that way ([[D002]]); null is already
specified as "the writer had no reason to give", and D5 classifies it as unattributable, so
the existing stream reads correctly under the new rules without being touched.

Rollback is the commit, and nothing persists a three-state verdict — the detector is invoked,
never resident, and holds no state between runs.
