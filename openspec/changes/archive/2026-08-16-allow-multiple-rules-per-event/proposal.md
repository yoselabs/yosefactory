## Why

Two legitimate writers can close the same question one second apart. Denis answers at 17:00:02;
the sweeper, which read the log before 17:00:02 and cannot make read-then-write atomic, appends
`timed_out` at 17:00:03. Neither actor misbehaved, and the log then fails to read until a human
repairs it by hand. In an unattended system a rare loud fault that needs hand repair is a stall
wearing a small hat.

The fold cannot currently express the fix. `Declaration.rules` maps one event name to exactly one
`Rule`, and `_check_from` rejects every event arriving from a terminal state unless
`from_states is ANY`, so `timed_out` cannot be *both* `awaiting → timed_out` and
`terminal → no-op`:

| rule for `timed_out` | normal case | late, after `answered` |
|---|---|---|
| `awaiting → timed_out` (today) | legal | fails the read |
| `{awaiting, answered} → timed_out` | legal | fails — the terminal check runs first |
| `ANY → no-op` | loses the transition | absorbs, but silently |

**Promotion id.** This refines **M600** (the typed question) and the two formats archived against
it. The dispatch that carried it did not name an id for the race finding itself — YF-2 probed it
against the built fold rather than reasoning about it — so there is no promotion id to cite for
that part, and one should be minted in K against M600.

## What Changes

- **The fold accepts one *or more* rules per event, and the first rule whose `from_states`
  matches the current state wins.** A bare `Rule` stays legal, so the item declaration is
  untouched. This adds no vocabulary: "one event, several legal shapes depending on where you
  are" is what a transition table already means.
- **The blanket terminal guard in `_check_from` moves into the `ANY_NON_TERMINAL` branch,** which
  is the only place it was ever load-bearing. A `frozenset` of non-terminal state names can never
  match a terminal state anyway, so this is behaviour-preserving for every existing rule — and it
  is what makes a rule able to name terminal states explicitly.
- **`timed_out` gains a second rule: from the terminal set, no state change.** The late sweeper
  record is retained, visible, and changes nothing.
- **A second `answered` under a different `event_id` still fails the read**, loudly. This is not a
  retreat to blanket tolerance; the spec states the discriminator so a later author cannot read it
  as one.
- **The question declaration is committed** to `protocol/question.py` with a test that folds the
  fixtures under `make check`. It exists today only as prose in two specs and a snippet in
  `questions/examples/README.md` — and that snippet is already wrong (`noted` scoped to
  `awaiting`, where the spec and the item declaration both say any state). The change cannot be
  demonstrated against fixtures without it.
- **A fifth fixture**: an answer at T, a sweeper `timed_out` at T+1s, folding to `answered`.
- **`TurnRecord` gains a `failure_kind` sibling field**, null unless `outcome` is `failed`, drawn
  from a closed executor-facing set. Today the executor's richer vocabulary —
  `budget_exhausted`, `turn_limit`, `cancelled`, and `failed(auth | rate_limit | crash |
  bad_output | task_error | version_mismatch)` — collapses to bare `failed`, and the reason
  travels in `note` as free text that nothing can query. **`rate_limit` must never fold into a
  generic failure** (`architecture.md` §7b rule 3): the model draws from the same rolling window as
  the operator's own interactive use, so a **starved** factory and a **broken** one are different
  conditions, and as the record stands they are the same row. Two axes, one record: `outcome`
  answers *did the turn advance* and is frozen; `failure_kind` answers *why did it fail* and is
  vendor-shaped and expected to change. Widening `outcome` would conflate them.
- **BREAKING (format, pre-first-run): `deadline` and `on_timeout` leave the item's `awaiting`
  block for `kind: question` and `kind: request`.** There they are duplicated on the question —
  two representations of one fact, the exact shape that demoted `terminal` from a state to a
  predicate. **They stay on `kind: item`,** where no question exists to hold them: nothing is
  duplicated, and removing them would remove the only bound the block has and let it hang forever
  (S172 — every loop must close). The duplication argument applies only where the fact has another
  home.

### The rule this encodes

> **Reject what could only come from a bug. Absorb what a correct actor could legitimately have
> written — and declare each such case explicitly.**

The discriminator is *could a correct actor have written this*, never *is the target terminal*. Its
operational test — the checkable form, and the one the spec states normatively — is **could the
writer have avoided the race?** A sweeper reads the log and appends as two steps and cannot fuse
them. A canceller or an answerer is deliberate and has already read the log it is closing. That
draws the line at *structural inability* rather than at good faith.

Dedup on `event_id` already makes a **retried** close idempotent, so tolerance buys nothing for
retries: a second close under a *different* `event_id` is a genuine double-write.

## Capabilities

### New Capabilities

None. The multi-rule semantics are stated in the requirement that demands them
(`question-frame`), not in a new capability of their own — the shared fold has never had its own
spec and giving it one here would state the same contract in a third place.

### Modified Capabilities

- `question-frame`: the declaration becomes a list of rules per event; `timed_out` absorbs from
  terminal; the reject-versus-absorb discriminator is stated normatively; the sweeper's no-op
  stops being an instruction to writers and becomes a property of the declaration.
- `backlog-item-format`: `awaiting` stops repeating `deadline` and `on_timeout` for `kind:
  question` and `kind: request`, keeps them for `kind: item`, and no longer requires them
  unconditionally.
- `run-guardrails/turn-record`: a record may carry `failure_kind`, the second axis. The four-value
  `outcome` enum is untouched — that is the point of the field.

## Impact

- `src/yosefactory/protocol/eventlog.py` — rule selection, `Declaration.rules` type.
- `src/yosefactory/protocol/question.py` — **new**, the committed question declaration.
- `src/yosefactory/protocol/backlog.py` — `_AWAITING_FIELDS` only. The `awaiting.on_timeout`
  pattern **stays**: patterns are checked only when the field is present, so it validates an
  item-kind block and is silent on a question-kind one. That is the whole conditional behaviour the
  declaration can express, and it happens to be the half worth having.
- `src/yosefactory/protocol/turn.py` — `FailureKind`, the `TurnRecord` field, `to_dict`,
  `from_dict`. The field is keyword-defaulted to `None`, so every existing writer — including
  `runtime/supervise.py`, which is another worker's file this round — keeps compiling untouched.
- `tests/protocol/` — new fold tests, new question-fold tests, new `failure_kind` tests. Exactly
  **one** test in `test_backlog_blocked_until.py` asserts the removed requirement (that a block
  without a `deadline` fails the read) and is rewritten. The `on_timeout` pattern test and the
  three-policies test survive untouched, because the pattern stays and present fields stay legal.
- `questions/examples/` — a fifth fixture; `README.md`'s declaration snippet and its "not
  committed anywhere yet" note; `questions/README.md`'s declaration section.

## Non-goals

- **`Rule.invariants` for cross-field predicates.** YF-1 designed the shape; it is a debt on a
  later dispatch. This change does not need it: `deadline` and `on_timeout` are *present* on an
  item-kind block rather than conditionally required, and whether a writer must emit them stays
  writer-enforced until that debt lands. Present-but-unenforced is strictly better than absent. The
  one thing still wanting it is `on_timeout: default:<answer>` being legal *for this question*.
- **`cancelled` absorbing from terminal.** The clock-race argument reaches it — a cancel landing a
  second after an answer — but it fails the discriminator's operational test: a canceller is
  deliberate and could have avoided the race by reading the log it was closing. Excluded on
  principle, not by omission, and the spec says so.
- **Dropping `who` and `nudge_at` from `awaiting`.** The same duplication argument reaches them.
  Not dispatched.
- **Blanket tolerance anywhere.** No event becomes legal from a state nobody named.
- **Retiring the `note` workaround in `executor/outcome.py`.** `RunResult.note()` carries the
  failure kind until the field exists. Retiring it belongs to the executor's owner, not here —
  `executor/` is another worker's this round.
- **Teaching the stall detector to read `failure_kind`.** This change makes starvation queryable;
  acting on it is a separate change against `run-guardrails/stall-detection`.
- **A `failure_kind` for `blocked`.** `needs_approval` and `refused` both collapse to `blocked`,
  and they demand different responses too. Same shape of gap, not dispatched. Reported.
- Fixing the stale spec pointer in `questions/README.md` (it names the pre-archive path).
  Reported, not touched.
