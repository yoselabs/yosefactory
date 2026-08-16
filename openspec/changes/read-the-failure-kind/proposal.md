# Proposal — read-the-failure-kind

**Promotion id:** none. This change is not a promotion from P160; it is a debt raised by the
build, against `architecture.md` §7b rule 3 (`rate_limit` may never fold into a generic
failure) and the handoff recorded in `implement-claude-executor`'s proposal, which dispatched
`TurnRecord.failure_kind` to "whoever holds the record" and predicted that until it landed,
rule 3 would be honoured in `RunResult` and degraded at the record boundary. It landed. It is
still degraded, for a reason that prediction did not anticipate.

## Why

`failure_kind` exists, validates, and round-trips — and **no writer ever populates it.** All
three `TurnRecord` construction sites were inspected; the two that author records omit the
argument, and the third is a reader. Every record the system can produce carries
`failure_kind: null`.

So the dispatched debt — the stall detector does not read the field — is real but downstream
of a larger one. Teaching the detector to branch would pass its own tests and change nothing
about any stream on disk, which is this repository's signature failure and the reason it
built a stall detector in the first place: a green check over an empty measurement.

The distinction being lost is the one rule 3 protects. A factory starved of quota and a
factory whose model is broken demand opposite actions — wait, versus fix — and [[D014]]'s
breach protocol makes root-causing mandatory and patching the gap forbidden, so an alarm that
misnames starvation as breakage spends a real investigation on a healthy factory.

## What Changes

**1. The kind gets a writer.** `runtime/turn.py` maps the executor's result to a typed
`failure_kind` and passes it to `TurnRecord`. The mapping covers the run-level `RunOutcome`
stops as well as the typed executor kinds, which finally gives `budget_exhausted`,
`turn_limit` and `cancelled` a producer — today nothing in `src/` even imports
`protocol.turn.FailureKind`, so the union's three widest values are unreachable in principle.

**2. The detector reads it, in two classes rather than nine branches.** One predicate beside
`counts_as_progress` in `protocol/turn.py`, over a two-member set:

```
starved   rate_limit, budget_exhausted                      → wait
broken    auth crash bad_output task_error version_mismatch → fix
          turn_limit cancelled
```

`auth` is filed as broken deliberately: it looks like starvation from outside and is fixed by
a human, never by waiting.

**3. Starvation renames the alarm; it never silences it.** The `Verdict` gains a third state.
`OK` exits 0, `STALLED` exits 1, `STARVED` exits 2 — both alarm states non-zero, distinct
codes so a scheduler can page on one and notify on the other without parsing prose. A factory
permanently out of quota produces nothing, and this module has already ruled against the twin
of the suppression argument: `nothing-ready` is not success. `budget_exhausted` is
`nothing-ready` wearing a reason.

`STARVED` requires no `advanced` in the window, at least one starvation position, and every
non-gap position being a starvation failure. One `crash` among starved turns is `STALLED` —
something is also broken and the broken thing is actionable. A gap is `STALLED` — a position
with no record has no kind, and an unattributable position may not be excused as starvation.

**4. The workaround retires, and it is not the one that was named.** `RunResult.note()` is
confirmed retirable: no production caller, one test reference. The correction is that it was
never installed — the record path never called it and hand-rolled its own string instead. The
**live** workaround is `runtime/turn.py:397`, which holds the typed kind and stringifies it
into free text one line before constructing a record with a typed field for it. Both go.

**5. Scope item, argued rather than assumed — the supervisor records its own reason.**
`govern()` knows exactly why it killed a run, and `turn_limit` is already in the union.
Withholding it makes the harness's own stops the least legible failures in the stream, and
they are the ones most likely to recur. Proposed: a turn-ceiling kill records `turn_limit`.
Null stays legal and stays the right answer where the writer genuinely does not know. **This
item is separable — strike it and the rest of the change stands.**

## Non-goals

- **No new failure kind.** The union is already wider than its producers; a wall-clock kill
  therefore maps to null rather than to a tenth value, and says so in the note.
- **No widening of `Outcome`.** Four words, frozen. Two axes, never one field.
- **No quota-aware retry, backoff, or scheduling.** Knowing a run was starved is not
  permission to build something that waits — that is [[D111]]'s daemon.
- **No alarm suppression, under any window composition.**
- **No change to what counts as progress.** `counts_as_progress` is untouched; only the
  naming of a non-progressing window changes.
- **No backfill of existing records.** Every record on disk carries null and stays that way
  ([[D002]]); null is already specified as "the writer had no reason to give".

## Known debts, owned by name

- **The window is not a neutral instrument**, and this change does not fix it. A quota outage
  lasting N turns pushes the last real trial out of the fixed window, so the detector reports
  on a window containing no evidence. Naming the verdict `STARVED` makes that legible and
  does not make it false. A window that skips starved positions is the candidate fix and is
  deliberately not proposed here — it would be a second measurement change landing at the
  same time as the first, with no stream on disk to read either against. Related to S187 in
  shape (the instrument is affected by the condition it measures), but not an instance of it:
  nothing here observes its own writes.
- **`ledger/runs/` still does not exist.** No run has ever been supervised. This change is
  verified by tests over synthesised streams, as its predecessor was. The first real record
  remains the first contact with reality.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `run-guardrails/stall-detection`: the detector classifies a non-progressing window as
  starved or broken and reports a third state with its own exit code; starvation never
  suppresses the alarm.
- `run-guardrails/turn-record`: a writer that knows why a turn failed SHALL record the typed
  kind rather than narrate it in the note. Null remains legal where the writer does not know.

## Impact

| File | Change |
|---|---|
| `src/yosefactory/protocol/turn.py` | add the starvation predicate beside `counts_as_progress` |
| `src/yosefactory/runtime/turn.py` | map `RunResult` → `failure_kind`; pass it through `_finish`; drop the f-string workaround |
| `src/yosefactory/runtime/stall.py` | three-state verdict, exit code 2, report names starvation |
| `src/yosefactory/runtime/supervise.py` | scope item 5 only — `turn_limit` on a ceiling kill |
| `src/yosefactory/executor/outcome.py` | remove `RunResult.note()` |
| `tests/executor/test_stream.py` | retarget the one `note()` assertion to the typed field |
| `tests/{protocol,runtime}/` | new cases for the predicate, the writer, and the three states |

**Concurrency, for the director rather than for me.** `executor/outcome.py` belongs to
`implement-claude-executor`, which reports complete but is **not archived**. Removing
`note()` edits a file inside another worker's live change directory's scope. Under Article IV
that is not mine to decide: either that change archives first, or item 4's `note()` removal
is deferred. The rest of item 4 — the `runtime/turn.py` f-string, which is the workaround
that was actually load-bearing — is entirely within this change's files.
