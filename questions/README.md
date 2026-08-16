# `questions/` — the durable typed question

A branch that cannot proceed writes a question here, and dies. An answer appended later resumes
exactly that branch, and only that branch.

**Normative source: `openspec/changes/define-question-frame-format/specs/question-frame/spec.md`**
(after archive: `openspec/specs/question-frame/spec.md`). This file is the working summary; where
the two disagree, the spec wins.

Design record: M600 (the mechanism), D020 (a request is the same object), S099 (branch-level
halting is correlation-id based), S172 (every loop must close), `architecture.md` §5.

## Layout

```
questions/
  q-20260816T171204Z-3f9a2c1d.jsonl    one file per question
  examples/                            worked examples, one per spec scenario
```

One file per question. Append-only, one JSON record per line. Nothing is ever rewritten or
deleted (D002). Two branches suspending at the same time write two different files, so
concurrent suspension needs no locking and produces no merge.

## The correlation id

```
q-<YYYYMMDD>T<HHMMSS>Z-<8 hex>        e.g. q-20260816T171204Z-3f9a2c1d
```

The id is the filename stem and is repeated in every record in the file. An answer names its
question by `qid`, which makes the target a path — no index, nothing to fall out of date. The
timestamp prefix sorts chronologically in a plain `ls`; the random suffix makes it unique
without coordinating with other writers.

An answer whose `qid` matches no file is an orphan: it closes nothing.

## Records

Every record carries `event`, `event_id`, `ts` (RFC3339, UTC), `actor`, `qid`, and `v`. The first
four are what the shared fold requires of any log; `qid` is this format's addition and `v` is the
schema version.

| `event` | Meaning | Terminal |
|---|---|---|
| `asked` | the question. Exactly one, and it opens the log | no |
| `nudged` | a reminder was sent | no |
| `noted` | context added, legal at any time including after closing | no |
| `answered` | answered | **yes** |
| `timed_out` | the deadline passed and the pre-registered policy fired | **yes** |
| `cancelled` | withdrawn — the question stopped being worth asking | **yes** |

`asked` also carries: `item` (the backlog item it suspends), `kind`, `to`, `text`,
`answer_type ∈ text | choice | bool` with `options` for `choice`, `context` (what an answerer
needs), `return_to` (the state the branch resumes into — decided now, not inferred later),
`resume_ref` (opaque harness token; readers must not interpret it), `nudge_at`, `deadline`,
`on_timeout`.

`answered` carries `verdict ∈ accept | reject`. A `reject` must carry `cause` and
`next ∈ retry | escalate | terminal` — a rejection is a reply, and a no that leaves the asker
nowhere to go violates S172.

## It runs on the shared fold

There is one fold in this repo (`protocol/eventlog.py`), and it knows nothing about questions.
Each kind of log supplies a declaration — initial event, states, terminal set, transition table —
and questions supply this one:

- `initial`: `asked`
- `states`: `awaiting`, `answered`, `timed_out`, `cancelled`
- `terminal`: `answered`, `timed_out`, `cancelled` (a predicate, never a written state)
- `rules`: `asked` → `awaiting`; `nudged` leaves the state alone while awaiting; `noted` leaves
  it alone from any state, closed included; `answered`, `timed_out`, `cancelled` each move
  `awaiting` to their own name

That is D020 made structural: a request, a question, and a work item are one object in different
states, so a second parser would be a modelling error rather than a convenience.

## State is a fold, never a field

Fold the records in `(ts, event_id)` order — never by position in the file, since a merge may interleave appended lines:

- `awaiting` until the state reaches the terminal set
- duplicate delivery collapses on `event_id`: the same event twice is one event; the same
  `event_id` carrying *different* content fails the read rather than picking a winner

The fold is loud. An unknown event, an illegal transition, or a malformed line fails the read
instead of yielding a state that never existed. Tolerance is not needed for retries: a retried
close carries the same `event_id` and collapses, so a second close under a *different* id is a
genuine double-write rather than delivery noise — so a terminal event appended to an
already-terminal question is a fault to repair by hand, not a state to infer. Whoever appends a
terminal event reads the log first; a sweeper never times out a question that already closed.

## Closing, always

Every question carries a `deadline` and an `on_timeout`:

- `escalate` — re-ask, upward, of someone who can answer
- `default:<answer>` — an answer **pre-registered at ask time**, and required to be legal for
  this question then. It may not be chosen or edited afterwards.
- `abandon:<reason>` — close as terminal without an answer

Past the deadline with no terminal record, a sweeper appends `timed_out` carrying the policy's
outcome, so the loop closes the question itself. An answer arriving early terminates it first and
the sweeper is then a no-op — wake on timer *or* activity, whichever comes first, without the two
coordinating.

## Kinds

Seven, closed:

| kind | blocking |
|---|---|
| `decision` | by failure |
| `ambiguity` | by failure |
| `out-of-depth` | by failure |
| `gate-failed` | by failure |
| `cost-approval` | by failure |
| `elicitation` | **by design** |
| `goal-falsified` | by failure |

Blocking-by-design questions are schedulable in advance; the rest arise from something going
wrong. The property is derived from `kind`, never set by hand.

**Kind routes a question. It never gates one.** Nothing may refuse, discard, or defer a question
because its kind was unexpected for the stage that emitted it, and no stage declares in advance
which kinds it may emit. S062 measured the alternative: eleven hand-authored `suspend_when`
clauses across two workflows, zero fired, and the one real suspension matched none of them.

## Who answers is a field

`to ∈ denis | loop:<name> | check:<name>`. A request made of another loop is an ordinary
question with a different `to` — same schema, same storage, same lifecycle (D020). If requests
ever grow their own schema, routing, or state, D020's justification evaporates and the decision
must be revisited rather than worked around.

A one-to-many announcement that expects no reply is **not** a question and does not belong here.
Nothing waits on it, so it is not an open loop.
