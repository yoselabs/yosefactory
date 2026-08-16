# Exploration — read-the-failure-kind

Dispatched as two debts, "probably one change". It is one change, and the first debt is
larger than dispatched: the detector cannot read `failure_kind` because **nothing writes it**.

## Ground truth, verified rather than assumed

| Claim | Verified how | Result |
|---|---|---|
| The stall detector ignores `failure_kind` | read `runtime/stall.py` in full | true — it reads `Position.outcome` only |
| `RunResult.note()` is retirable | `grep -rn "note()" src tests openspec` | true, and for a stronger reason — see F3 |
| `failure_kind` is written by some producer | `grep -rn "TurnRecord(" src` and inspected all three | **false** — no producer exists |
| The union's extra values have a producer | `grep -rn "from yosefactory.protocol.turn"` across `src/` | **false** — no module in `src/` imports `protocol.turn.FailureKind` |

## F1 — the field has no writer

`TurnRecord` is constructed in exactly three places:

| Site | Passes `failure_kind`? |
|---|---|
| `runtime/turn.py:465` (`_finish`) | no |
| `runtime/supervise.py:210` (`govern`) | no |
| `protocol/turn.py:193` (`from_dict`) | yes — from a payload |

`from_dict` is a reader. It round-trips a value that no writer originates. Every record the
system can currently produce carries `failure_kind: null`, so **teaching the detector to
branch on the field would be a no-op against real data** — it would pass its own tests and
change nothing about any stream on disk.

This is the second appearance in this repository of *authoring is not persisting*, and it
landed twice in the same direction within one field's lifetime: a method authored and never
installed (F3), and a field authored and never populated (F1).

## F2 — the union is wider than anything that can fill it

Two vocabularies, and the gap between them is the whole justification for the union:

```
protocol.turn.FailureKind   9   budget_exhausted turn_limit cancelled
                                auth rate_limit crash bad_output task_error version_mismatch
executor.outcome.FailureKind 6                  auth rate_limit crash bad_output task_error version_mismatch
                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                these three are RunOutcome values, not executor FailureKinds
```

`protocol/turn.py` documents this correctly: the run-level stops all narrow to `FAILED`
carrying no reason of their own, so a set mirroring only the typed kinds would leave a
starved run indistinguishable from a broken one. That is right, and **the function that
performs the flattening does not exist.** `RunOutcome.BUDGET_EXHAUSTED` is never turned into
`FailureKind.BUDGET_EXHAUSTED` anywhere.

**Revised after YF-4's measurement, 2026-08-16.** The first draft of this finding said the
distinction was unreachable *in principle*. That was wrong in the direction that matters: it
is reachable and **reported**, not inferred. `terminal_reason` is a native field on every
terminal event — `budget_exhausted` against `completed` — and `--max-budget-usd` exists on
this binary at this version, which falsifies S183's *nine surfaces, zero cost caps* on this
surface. Confirmed here by reading, not taken on report: `classify` in `executor/stream.py`
derives from `subtype`, `api_error_status`, `stop_reason` and `permission_denials`, and the
string `terminal_reason` appears nowhere in that module.

**And the field is already on disk in this repository's own test data.** The success fixture
at `tests/executor/test_stream.py:27` carries `"terminal_reason": "completed"`. It was
captured and never read. Third instance of *authoring is not persisting*, and the cheapest
one to have caught.

## F2b — starvation is not merely unread, it is actively misfiled

Worse than the gap above, and found while verifying it. `classify` has a branch for
`error_max_turns` and none for `error_max_budget_usd`. A budget-exhausted terminal event
therefore falls through every branch to the final line:

```python
return RunOutcome.FAILED, FailureKind.TASK_ERROR, subtype or "the agent reported an error"
```

So today a starved run is not recorded as an unknown reason. It is recorded as
`task_error` — the most generic *broken* value in the set. §7b rule 3 forbids folding
`rate_limit` into a generic failure; its sibling is being folded into one right now, at the
first hop, before the record boundary the whole handoff was concerned with. The narrowing
that loses the distinction happens one layer earlier than anyone was watching.

## F3 — debt 2, verified, with a correction

`RunResult.note()` has **no production caller**. Its only reference in the repository is one
test assertion, `tests/executor/test_stream.py:141`.

The correction to the dispatch: it is not a workaround that outlived its purpose. It is a
workaround **that was never installed**. Its docstring promises it carries the kind "until a
record can hold it as a typed field of its own" — but the code that builds the record,
`runtime/turn.py:397`, never called it. It hand-rolled a different string instead:

```python
return failed(f"executor reported {result.outcome.value} ({result.failure_kind or 'no kind'}): {result.detail}")
```

So retiring `note()` deletes dead code and recovers nothing. **The live workaround is that
f-string** — it holds the typed value in its hand and stringifies it into free text one line
before constructing a record with a typed field for exactly that value. That is the thing
worth retiring, and the dispatch did not name it because it is not where anyone would look.

## F4 — the window is not a neutral instrument

Not S187, but its relative, and worth naming before it is designed around.

A `rate_limit` or `budget_exhausted` position is not evidence about factory health. It
records that the factory was **prevented from trying**. But it consumes a slot in the fixed
window of N. So:

```
quota outage lasting >= N turns
      │
      ▼
window fills with positions that carry no evidence
      │
      ▼
the last real trial is pushed out of the window
      │
      ▼
detector fires STALLED on a window in which it knows nothing
```

The alarm is loudest exactly where it has least information. Nothing here observes its own
writes, so it is not S187 — the shape it shares is that **the measuring instrument is
affected by the condition being measured**.

## F5 — what the detector should do per value: two classes, not nine

The detector's question is not *why did this turn fail*. It is *does a human need to act, and
how*. That collapses nine values to two.

| Class | Values | Operator action |
|---|---|---|
| **starved** | `rate_limit`, `budget_exhausted` | wait, or buy quota |
| **broken** | `auth`, `crash`, `bad_output`, `task_error`, `version_mismatch`, `turn_limit`, `cancelled` | fix something |

Two placements are deliberate and could go the other way:

- **`auth` is broken, not starved.** An expired token looks like starvation from outside —
  requests stop — and is resolved by a human, never by waiting. Filing it as starvation would
  make the one failure a human must act on the one the alarm tells them to sit out.
- **`turn_limit` and `cancelled` are broken.** They are the harness's own stops. They say a
  configured bound fired, which is a configuration question and actionable.

Getting this wrong is not free. [[D014]]'s breach protocol makes root-causing the platform
mandatory and forbids patching the gap, so an alarm that says *broken* when the truth is
*starved* spends a real investigation on a healthy factory.

## F6 — starvation must never silence the alarm

The tempting move is to suppress the alarm on a starved window. It is wrong, and this module
has already ruled against its twin: `nothing-ready` is not success, because a long run of
non-errors that produced nothing is the exact failure the detector exists to catch. A factory
permanently out of quota produces nothing. **`budget_exhausted` is `nothing-ready` wearing a
reason.**

So starvation changes what the alarm *names*, never whether it fires. Three states:

```
                                          exit
  an `advanced` in the window        OK     0
  no advance, window not starvation  STALLED 1    fix something
  no advance, window is starvation   STARVED 2    wait — still not healthy
```

Both alarm states are non-zero. That is the load-bearing part; the distinct codes exist so a
scheduler can page on one and notify on the other without parsing prose.

Precise condition for STARVED, chosen to avoid inventing a threshold: no `advanced` anywhere
in the window, **and** at least one starvation position, **and** every non-gap position in
the window is a starvation failure. Anything else is STALLED, including:

- **a single `crash` among starved turns** — something is also broken, and the broken thing
  is the actionable one;
- **any `nothing-ready` or `blocked`** — the factory was free to try and had nothing to do,
  which is a stall, not starvation;
- **any gap.** A position with no record has no kind, and an unattributable position may not
  be excused as starvation. This follows the existing rule that a missing record is a failure
  and never missing data.

## What explore did not overturn

- The four-word `Outcome` stays frozen and unwidened. Two axes, never one field.
- `failure_kind` stays nullable, and null stays legal for a supervisor authoring on behalf of
  a process it killed. One narrowing is proposed (below) and it does not make null illegal.
- No new failure kind is introduced. The union is already wider than its producers.

## Open questions carried into the proposal

1. **Should the supervisor record its own reason?** *Resolved: yes, adopted by the director.*
   `govern()` knows precisely why it killed a run — wall clock or turn ceiling — and
   `turn_limit` is already in the union. Withholding it makes the harness's own stops the
   least legible failures in the stream and they are the ones most likely to recur.
2. **The wall-clock kill has no value in the union.** A turn-ceiling kill maps to
   `turn_limit`; a wall-clock kill maps to nothing. Default taken: leave it null rather than
   add a tenth value, and say so in the record's note.

## F7 — a report about `enforced_by` checked against disk, and it does not hold

The dispatch warned that on a wall-clock stop the agent flushes a terminal event inside the
grace window, so `verdict()` answers and `govern` writes `enforced_by: agent` for a run the
harness killed — a mis-attribution not to inherit.

**Checked before revising against it (Article XII), and `supervise.py` already rules the
other way.** The `stop.by_harness` branch is evaluated *before* the flushed verdict and wins
unconditionally, with a comment citing the same measurement:

> A stopped run is the harness's ending regardless of what the agent managed to say. […] who
> stopped the run decides who authored the ending.

Landed in `2a08238`, *"guardrails: who stopped the run decides who authored the ending"*. The
hazard is real and was closed; the report describes the code before that commit. Nothing to
inherit and nothing to fix — recorded here so the next reader does not "fix" it back.
