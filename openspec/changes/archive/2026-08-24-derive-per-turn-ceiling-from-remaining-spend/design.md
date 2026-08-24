## Question

Should an unattended run be allowed to set a cumulative ceiling (`--spend-ceiling-usd`) and no
per-turn ceiling (`--cost-ceiling-usd`) at all? Three options were on the table:

**A. Require `--cost-ceiling-usd` whenever `unattended=True`, the same way `--spend-ceiling-usd`
is already required.** Rejected. It pushes the decision onto every caller and gives no guidance on
*what number* to pass — a caller could set `--cost-ceiling-usd 100` alongside `--spend-ceiling-usd
2.00` and satisfy the requirement while reproducing S244 almost exactly (one turn spends up to
$100 before the cumulative check ever sees it). Requiring the flag's presence is not the same as
requiring it to be small enough to matter, and there is no natural default to enforce the second
part with — it would need this very derivation anyway, at which point the requirement is dead
weight on top of it.

**B. Refuse to start unattended with a cumulative ceiling and no per-turn bound.** Rejected for the
same reason as A, plus a new one: it changes `main(unattended=True)` from "runs, with a gap" to
"refuses to run", which is a bigger behavior change for a bigger class of existing invocations
(every one that only sets `--spend-ceiling-usd`, which per S244 is exactly the shape the dev
compose file used) than deriving a number silently and safely.

**C. Absent an explicit per-turn ceiling, derive one from the cumulative remaining budget before
each turn.** Chosen. It requires no new argument, breaks no existing caller (a caller that sets
neither flag, e.g. `main(unattended=False)`, is untouched — the derivation is gated on
`spend_ceiling_usd is not None`, which is D022 §3's own boundary: a program-wide cost ceiling stays
deferred exactly on the path where a human is present), and it closes the gap this signal exists to
close: nothing that only sets a cumulative ceiling can any longer let one turn run cost-unbounded.
Explicit callers (`take-a-turn.yml`, which already passes both from one number) see identical
behavior — the derivation only fires when `cost_ceiling_usd` is `None`.

## What "derive" means, precisely

Before each turn, if `bound.spend_ceiling_usd is not None` and `limits.cost_ceiling_usd is None`:

```
remaining = bound.spend_ceiling_usd - spend_recorded_so_far()
turn_limits = replace(limits, cost_ceiling_usd=remaining)
```

`remaining` is always strictly positive at this point: the loop already refuses to start a turn
once `spend_recorded_so_far() >= spend_ceiling_usd` (the existing check, unchanged, immediately
above this one). `Guardrails.__post_init__` already refuses a non-positive `cost_ceiling_usd`, so
this can never construct an invalid `Guardrails`.

`limits` itself (the caller's own `Guardrails`) is never mutated — a fresh `replace()`d copy is
built per iteration and handed to that iteration's `take_turn` call only. A caller that reads back
its own `limits` after `run_loop` returns still sees what it passed in.

## What this does not claim to fix

`--max-budget-usd` (`claude-executor/cost-ceiling`) is a **post-hoc detector inside the `claude -p`
process**, not a preventive bound: it stops the next *internal* step once a cumulative figure is
crossed, and does not interrupt the step already running. This was measured directly ($0.02 cap,
$0.048 observed — 2.4x) before this change existed and is unrelated to it. Deriving a tighter
number from the remaining budget makes the *default* case (nothing explicit set) exactly as
bounded as the best case anyone could get by hand-tuning `--cost-ceiling-usd` themselves; it cannot
make the underlying flag interrupt a turn that is already inside an expensive step, because no
version of the pinned binary can do that (`EMULATED`/`NATIVE` tables, `executor/claude.py`).

**Unresolved by this change, and worth a live receipt separately:** whether a derived cap close to
the full remaining budget (e.g. a fresh loop's first turn, where `remaining == spend_ceiling_usd`)
meaningfully changes anything at all for that first turn — it does not, by construction, and that
is correct: the point is to shrink the ceiling as the budget is consumed, not to add a bound where
none was requested for the first turn of a fresh run. A run that spends its entire cumulative
budget inside one very expensive first turn is still exposed to whatever multiple the detector's
own overshoot is (measured 2.4x elsewhere, not reverified here) — this change narrows the window
S244 found (turn 2 of a multi-turn run), it does not eliminate the executor's own detector-not-
preventer property.

## Alternative considered and rejected: clamp explicit values too

Considered clamping an *explicit* `cost_ceiling_usd` down to `remaining` as well, so a caller could
never set a per-turn number larger than what is left. Rejected: `take-a-turn.yml`'s own comment
names the two flags as equal by deliberate choice, and a caller that explicitly sets both is making
an informed choice this change has no basis to override. The derivation exists to supply a number
when none was given, not to second-guess one that was.
