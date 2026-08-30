# ADR-0022 — `falsified` should join `TERMINAL`; `needs_split` should not, yet

**Status:** Accepted (recommendation only — `TERMINAL` is unchanged by this ADR)
**Date:** 2026-08-30
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** an operator (or a workflow) needs to know "are this `needs_split` item's
children all done yet" and finds no answer, or a rollup-on-children-complete mechanism is proposed
— either is the moment `needs_split`'s case should be reopened, not before.

## Context

four-dead-ends found thirteen backlog states with four reachable, non-terminal dead ends: `woke`,
`snoozed`, `falsified`, `needs_split`. This change built sweepers for the first two and for
retryable `failed` (a fifth dead end the same audit found, one door short of terminal rather than
missing a sweeper). `falsified` and `needs_split` are different in kind from all three: nothing is
missing a writer. Both already carry the field that names where the work went (`successor`,
`children`) the moment they enter the state. The open question is not "what fires the transition"
— it is "should `TERMINAL` (`architecture.md §3`, five states today: `done`, `cancelled`, `poison`,
`duplicate`, `abandoned`) include them," which is a change to what every reader of `terminal`
sees, not an implementation detail this change is scoped to decide by itself.

`terminal` is a derived predicate, never a state (`backlog-item-format`'s own framing): the
question is not whether these two items are "finished" in some loose sense, but whether the format
should assert, structurally, that no future event can legally land on them (`No event SHALL be
accepted against an item that is already terminal, except note` already carves out annotation
regardless of the answer here — `note` stays legal either way).

## The case for `falsified`

`falsified` requires `by` (the full falsification, not a reference) and `successor` (the id of the
item created to carry the work forward), written together in one append
(`backlog-item-format`'s "Falsification emits a successor and loses nothing"). From that moment,
every field on the falsified item is fixed — nothing about *it* changes as the successor
progresses; the successor's own log is where that progress is recorded. This is structurally
identical to `duplicate`, already terminal: `duplicate` requires `survivor`, the id of the item
that continues, and "the duplicate is terminal; the survivor is unaffected." Two closed-with-a-
pointer-forward records, one terminal and one not, is the asymmetry this ADR resolves — there is no
argument in the corpus for treating a 1:1 fork-and-continue differently depending on whether the
fork was "this was wrong" (`falsified`) or "this already exists" (`duplicate`).

No mechanism anywhere proposes a transition out of `falsified` other than creating a fresh
successor from a fresh `falsified` event on a *different* item — D002's append-only posture already
forbids reopening a closed record to redirect it, which is exactly what a `falsified -> anything`
transition on the *same* item would be attempting. There is no future feature this ADR can find
that needs `falsified` to stay open.

**Recommendation: add `falsified` to `TERMINAL`.**

## The case against `needs_split`, for now

`needs_split` requires `children`, a list, not a single id — the asymmetry that keeps this case
open. A 1:1 successor has nothing left to compute once the fork happens; a 1:many split has an
obvious future question a fork does not: *is the split done* — have all the children reached a
terminal state, and if so, does the parent have anything left to report (which children finished
which way, whether the split itself accomplished the goal). Answering that requires either (a) the
parent staying non-terminal until some later event closes it once children resolve, or (b) a
rollup mechanism nobody has designed yet that would itself decide what `needs_split`'s terminal
transition looks like and what it carries. Marking it terminal now forecloses (a) outright and
guesses at (b) without the evidence D021's posture asks for ("build the detector, learn the
condition, decide the limit later" — here: learn whether anything ever needs the rollup before
deciding how it closes).

The cost of leaving it open is bounded, not open-ended: `should_plan` already excludes `needs_split`
from suppressing planning (ADR-0012), so a parked split item costs nothing beyond sitting in the
backlog, exactly like `blocked`/`snoozed` did before their sweepers existed — except here there is
no missing sweeper to build, because there is no known-correct transition to fire. Silence is the
honest state until a real caller needs the answer.

**Recommendation: leave `needs_split` out of `TERMINAL`.** Documented here as a deliberate gap,
not an oversight — the revisit trigger above is what turns it back into a build task.

## Non-decision

This ADR states a case; it does not change `backlog.TERMINAL`, `STATES`, or any rule. Widening
`TERMINAL` is a protocol change (`architecture.md §3`, five states compared row-for-row against
every other) that touches every reader of `terminal` across this repository and needs its own
change, scoped to that edit alone, should the recommendation above be adopted.
