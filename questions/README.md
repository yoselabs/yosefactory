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

Every record carries `rec`, `qid`, `ts` (RFC3339, UTC), `actor`, and `v`.

| `rec` | Meaning | Terminal |
|---|---|---|
| `asked` | the question. Exactly one, and it is the first line | no |
| `nudge` | a reminder was sent | no |
| `note` | context added while awaiting | no |
| `answer` | answered | **yes** |
| `timeout` | the deadline passed and the pre-registered policy fired | **yes** |
| `cancel` | withdrawn — the question stopped being worth asking | **yes** |

`asked` also carries: `item` (the backlog item it suspends), `kind`, `to`, `text`,
`answer_type ∈ text | choice | bool` with `options` for `choice`, `context` (what an answerer
needs), `return_to` (the state the branch resumes into — decided now, not inferred later),
`resume_ref` (opaque harness token; readers must not interpret it), `nudge_at`, `deadline`,
`on_timeout`.

`answer` carries `verdict ∈ accept | reject`. A `reject` must carry `cause` and
`next ∈ retry | escalate | terminal` — a rejection is a reply, and a no that leaves the asker
nowhere to go violates S172.

## State is a fold, never a field

Fold the records in `ts` order (ties broken by line order):

- `awaiting` until a terminal record exists
- the **first** terminal record decides the state; later terminal records are kept and ignored

That rule is what makes a duplicated answer, an answer racing the sweeper, and a replayed board
event all produce the same state from the same bytes.

## Closing, always

Every question carries a `deadline` and an `on_timeout`:

- `escalate` — re-ask, upward, of someone who can answer
- `default:<answer>` — an answer **pre-registered at ask time**, and required to be legal for
  this question then. It may not be chosen or edited afterwards.
- `abandon:<reason>` — close as terminal without an answer

Past the deadline with no terminal record, a sweeper appends `timeout` carrying the policy's
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
