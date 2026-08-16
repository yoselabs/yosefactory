## Context

See `proposal.md` — Why. What matters for the approach is the shape of the fold as built:

```
_fold(records) per record:
    rule = declaration.rules[name]          one Rule per event name
    _check_from(rule, state, ...)           terminal guard, then from_states
    _check_payload(rule, record, ...)       the same rule's required + patterns
    _target(rule, state, arrivals, ...)     str | None | ReturnTo
```

`Declaration.rules` is a `Mapping[str, Rule]`. Two consumers exist: `backlog.ITEM` (nineteen
events, all single-rule) and the question declaration, which is not committed anywhere — it lives
as prose in `openspec/specs/question-frame/spec.md` and as a snippet in
`questions/examples/README.md` that was run from a scratch script.

## Goals / Non-Goals

**Goals**

- One event, several ordered rules, first match by `from_states` wins.
- A rule can name terminal states, so absorption is declared where it applies.
- No change to any existing `LogError` message, because three tests assert on them and the messages
  are the format's loudness in practice.
- The question declaration becomes code with a test over the fixtures.

**Non-Goals** (design-level, beyond the proposal's)

- No change to dedup, ordering, `ReturnTo`, or the parse layer.
- No new sentinel. `ANY` and `ANY_NON_TERMINAL` stay as they are, and nothing like `ANY_TERMINAL`
  is added — a rule that absorbs from terminal names the states it absorbs from.

## Decisions

### D1 — `rules: Mapping[str, Rule | tuple[Rule, ...]]`, normalized at read time

A bare `Rule` stays legal and means a one-element sequence. `backlog.ITEM` is then untouched:
nineteen events that have one legal shape keep saying so in one line.

*Alternative — every value becomes a tuple.* Uniform in the type, worse everywhere it is read:
nineteen single-element tuples that exist to satisfy a signature. Rejected.

*Alternative — a `Rule` holding several (from, to) pairs.* Moves the branching inside `Rule` and
gives one event two identities in one object; `required` and `patterns` would then have to be
per-pair anyway, which is the sequence again with extra nesting. Rejected.

### D2 — The terminal guard moves into the `ANY_NON_TERMINAL` branch, and this is behaviour-preserving

Today `_check_from` rejects any event from a terminal state before it ever consults `from_states`.
That guard is only ever load-bearing for `ANY_NON_TERMINAL`, and the reason is worth stating
because it is what makes the whole change small: **a `frozenset` of non-terminal state names cannot
match a terminal state.** For every existing frozenset rule, the guard and the membership test
reject exactly the same records — they differ only in the message. So the guard is not a safety
property being weakened; it is a special case that was standing in front of a test that already
covered it.

What must be preserved is the *message*. `test_backlog_fold.py` asserts
`illegal from terminal state 'cancelled'` for `claimed` after `cancelled`. So selection failure
checks terminality only to choose its wording:

```
select(rules, state):
    position 0            -> rules[0]           (no from-check; the initial event has one rule)
    first rule matching   -> that rule
    none matched, terminal-> "…is illegal from terminal state 'X'"      (unchanged text)
    none matched          -> "…is illegal from state 'X'; legal from: …" (unchanged text)
```

`legal from:` for a multi-rule event lists the union of the named states, sorted, so the message
stays a fact about the declaration rather than about which rule was tried.

*Alternative — keep the blanket guard and add an `ANY_TERMINAL` sentinel that bypasses it.* Two
mechanisms for one question ("does this rule apply here?"), and the sentinel would have to
bypass the guard the way `ANY` does, which is how the guard came to hide a whole class of
declarations in the first place. Rejected.

### D3 — Payload validation follows the selected rule, not the event name

The absorbing `timed_out` rule requires nothing; the transitioning one requires `policy` and
`answer`. That falls out of selecting first and validating second, and it is desirable: what a
record must carry depends on what it is doing. It also means a malformed record can be absorbed by
a later rule instead of failing — accepted deliberately, because the absorbing rule exists for
records whose content is irrelevant to the state.

### D4 — `timed_out` absorbs from the whole terminal set, not only from `answered`

The race is between a timer-driven writer and *any* deliberate close. A question cancelled one
second before the sweep is the same event as one answered one second before it. Two sweeper
instances racing each other is also the same shape, so `timed_out` after `timed_out` under a
different `event_id` is absorbed too — dedup already handles the retry of a single sweep.

### D5 — Why `answered` and `cancelled` keep failing, stated so it survives

The discriminator the proposal states — *could a correct actor have written this* — needs an
operational test or the next author will read it as taste. The test: **could the writer have
avoided the race?** A sweeper reads the log and appends as two steps and cannot fuse them, so it
cannot avoid it. A deliberate answerer or canceller has read the question it is closing; a second
one means two parties both believed they owned the close, which is the bug the loudness exists to
find.

This is also why `cancelled` is *not* given an absorbing rule here even though the clock-race
argument reaches it (a cancel landing a second after an answer). It was not dispatched, and unlike
the sweeper, a canceller is deliberate. Reported to the director rather than built.

### D6 — The question declaration is committed to `protocol/question.py`

The change is not demonstrable otherwise: the acceptance is stated over the fixtures, and nothing
in `make check` folds them today. It is data plus the declaration, mirroring `backlog.py`, and the
spec is already normative for its content, so this adds no design.

It also fixes a live defect. The snippet in `questions/examples/README.md` scopes `noted` to
`frozenset({"awaiting"})`, while the spec and the item declaration both make `noted` legal from any
state — the archived change's own task 6.2. Prose that nothing runs was wrong within a day.

### D7 — `failure_kind` is one flattened set, and the two executor vocabularies flatten cleanly

The executor loses information at two levels, not one. `RunOutcome` values
`budget_exhausted | turn_limit | cancelled | failed` all map to `Outcome.FAILED`, and only the last
of those carries a `FailureKind`. So a field that mirrored `FailureKind` alone would still leave
`budget_exhausted` as a bare `failed` — and `budget_exhausted` versus `rate_limit` is precisely the
starvation distinction §7b rule 3 is about.

So `failure_kind` is the **union**, flattened onto the one question *why did it fail*:

```
RunOutcome.BUDGET_EXHAUSTED / TURN_LIMIT / CANCELLED  -> that name
RunOutcome.FAILED + FailureKind.X                     -> X
RunOutcome.FAILED, no FailureKind                      -> null
supervisor-authored kill                               -> null, enforced_by: harness
```

The two vocabularies have disjoint names, so the union is unambiguous and a reader never needs to
know which level a value came from. `success`, `needs_approval` and `refused` never appear, because
they do not map to `failed`.

*Alternative — mirror `executor.FailureKind` exactly.* Tighter coupling and it fails the actual
requirement, per above. Rejected.

*Alternative — one enum in `protocol`, re-exported to the executor.* Inverts the dependency: the
vendor-shaped vocabulary would live in the frozen layer, which is the split `outcome.py`'s own
docstring exists to keep. Rejected.

*Alternative — add `wall_clock` for supervisor kills.* Would let `failure_kind` be non-null for
every `failed` record, but it invents a value the executor does not have, in a set declared
executor-facing. `enforced_by: harness` already answers who ended the run. Left null and
**reported**, not built.

`protocol/turn.py` owns the enum (it is a record field and `from_dict` must validate it), and
`executor/outcome.py` maps into it. The field is keyword-defaulted `None`, so `runtime/supervise.py`
and every existing test construct records unchanged — which is what keeps this change out of
`runtime/`, another worker's area this round.

## Risks / Trade-offs

- **Absorption spreads.** A future author reads "the fold tolerates late closes" and adds
  tolerance where the race is imaginary → the discriminator and its operational test (D5) are
  normative in the spec, and each absorbing rule must be declared, so spreading it requires
  editing a declaration and saying why.
- **A silent no-op hides a real bug.** A sweeper that is simply wrong about deadlines now appends
  records that change nothing and raise nothing → the record is retained and visible in
  `FoldedLog.records`; the fifth fixture makes that visibility the acceptance rather than a claim.
- **Payload-per-rule surprises.** A record that should have failed for a missing field instead
  matches an absorbing rule → accepted (D3); the absorbing rule applies only from terminal states,
  where the payload cannot affect the fold.
- **`failure_kind` drifts from the executor's enums.** Two closed sets naming overlapping things,
  in two layers, with no compile-time link → the mapping lives in `executor/outcome.py` where the
  vendor vocabulary already lives, so a new `FailureKind` value fails the mapping there rather than
  silently writing an unrecordable record. A test asserts every `FailureKind` value has a
  `failure_kind` counterpart, so adding one to the executor breaks a test rather than a record.
- **A null `failure_kind` reads as "no reason".** It means "the writer had no typed reason", which
  is a real distinction for supervisor-authored kills → stated normatively in the spec, since it is
  the kind of thing a consumer guesses wrong once and silently.
- **Three tests are rewritten, not broken.** `test_backlog_blocked_until.py` asserts the removed
  requirement (`deadline` required on `awaiting`, `on_timeout` pattern-checked, the three policies
  legal there). The spec removes it, so the tests move to the question declaration, which is where
  the fields now live. Net test count does not fall.

## Migration Plan

No stored data migrates. `ledger/` has no rows and the question fixtures are examples; the four
existing ones do not carry `deadline` on an item's `awaiting` block, because no item logs exist
yet. `backlog/fixtures/` items carry no `blocked` event — to be confirmed as task 1.1 rather than
assumed.

## Open Questions

Genuinely deferrable, and none of them change the specs or the task breakdown:

- **The promotion id for the race finding.** The dispatch named none; `proposal.md` cites M600 and
  says so plainly. K should mint one against M600 — the director's call, not a blocker here.
- **`who` and `nudge_at` on `awaiting`.** The duplication argument that moves `deadline` and
  `on_timeout` reaches both: `who` restates the question's `to`, and `nudge_at` restates the
  question's own. Not dispatched; left alone.

## The corrected `awaiting` rule, and why it is not a cross-field predicate

The dispatch first said the question owns `deadline`/`on_timeout` and the item never repeats them.
Explore found that this regresses `kind: item`: an `awaiting` naming another item has no question,
items carry no deadline of their own, and the duplicated fields were therefore the *only* bound on
that block. Stripping them ships a block that can hang forever, against S172. The director
corrected the dispatch; the rule is now:

```
awaiting.kind = question | request  ->  references the question; fields NOT repeated
awaiting.kind = item                ->  carries deadline/on_timeout itself; nothing else can
```

**The two-representations-of-one-fact argument applies only where the fact has another home.**

This needs no `Rule.invariants`, and the reason is worth stating because it looked like it did.
"Required when `kind` is `item`" is a cross-field predicate and is inexpressible. But the fields are
now *tolerated* rather than *conditionally required*: they are dropped from `required`, so a
question-kind block reads fine without them, and an item-kind block that carries them reads fine
too. Whether an item-kind writer *must* emit them stays writer-enforced until that debt lands.
Present-but-unenforced is strictly better than absent.

One piece of conditional validation does survive, for free: `_check_payload` skips a pattern whose
field is absent, so keeping the `awaiting.on_timeout` pattern validates the value wherever it
appears and stays silent where it does not. The half of the conditional behaviour worth having is
the half the declaration can already express.

**Still wanting `Rule.invariants`, and only this:** `on_timeout: default:<answer>` being legal *for
this question* — the pre-registration rule the question-frame spec states and no declaration can
check. Deferred to a later dispatch, not concurrent with this change.
