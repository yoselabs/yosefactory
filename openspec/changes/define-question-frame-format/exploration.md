# Exploration — define-question-frame-format

Worker YF-2. Dispatched 2026-08-16 by the K visionary session. Sources read: `CLAUDE.md`,
`P160/build-loop.md`, `P160/architecture.md` §5 and §7, `P160/dispatch-plan.md` change 2,
`M600`, `D020`, `S099`, `S075`. Written so a successor can resume from files alone.

## What the change is

The on-disk format for a durable typed question written by a suspended branch, and for the
answer that resumes exactly that branch. Format and its rules only — see Scope seam below.

## The decisive constraint

`S099`: branch-level halting is correlation-id based in every system that achieves it
(Step Functions task tokens, LangGraph `Command(resume={id: value})`, Temporal async
completion — all three directly verified in that signal's provenance audit). Anything that
pauses "the run" as a unit cannot let sibling branches continue. So the id is not a
convenience field; it is the mechanism, and the acceptance test is written against it.

`S099` also establishes the *pre-declared address* rule: no production system lets an agent
spontaneously decide mid-reasoning that it is unqualified, emit a question to a durable
location, and let its process die. The harness supplies suspend/resume
(`permissionDecision: "defer"`, `session_store`, `resume`, `fork_session`); the durable
question store is ours. This change is that store's format.

## Shape chosen

One file per question, append-only, one JSON record per line. The filename stem *is* the
correlation id.

```
questions/
  q-20260816T171204Z-3f9a2c1d.jsonl
  q-20260816T171331Z-b7e40a52.jsonl
```

Why one file per question rather than one shared log:

- `architecture.md` §4 — append-only one-record-per-line never conflicts, and mutable state
  is the fold of the log at read time. Both hold here.
- Two branches suspending concurrently write *different files*, so the concurrent case
  produces no merge at all rather than a merge that happens to resolve. Under
  `orchestration.md` Article III (one shared tree, invisible co-workers) that is the whole
  point.
- The correlation id is then discoverable by `ls`, and an answer's target is a path.

Records: `asked` (exactly one, first line), then any of `nudge`, `answer`, `timeout`,
`cancel`, `note`.

State is a fold, never a field:

```
awaiting ──answer──► answered
   │
   ├──timeout──► timed_out
   └──cancel───► cancelled
```

First terminal record wins; later terminal records are kept (D002: nothing is deleted) and
ignored by the fold. That is what makes duplicate delivery safe, and it is the same
consumer-offset discipline `architecture.md` §7 puts on board events.

## Wake on timer OR activity, whichever comes first

Not a scheduler feature — a property of the fold. The question is live until it holds a
terminal record. The sweeper turn appends `timeout` only if no terminal record exists once
`deadline` has passed. An answer arriving early terminates it and the sweeper no-ops. So
"whichever comes first" needs no coordination between the answerer and the sweeper.

`on_timeout ∈ escalate | default:<answer> | abandon:<reason>`, with the default answer
**pre-registered at ask time** and required to be a legal answer to this question — the same
discipline this program already uses for probe outcomes. On expiry the loop closes the
question itself, which is what makes `S172` ("every loop must close") self-enforcing rather
than aspirational.

`return_to` is **stored at ask time, not recomputed** (`architecture.md` §5, from Jira's
flag-versus-status argument): whoever suspends decides where resuming lands.

## Kinds

Closed set of seven, from `M600` plus the one the dispatch adds:

| kind | blocking | origin |
|---|---|---|
| `decision` | by failure | M600 (S036) |
| `ambiguity` | by failure | M600 (S043) |
| `out-of-depth` | by failure | M600 (S033) |
| `gate-failed` | by failure | M600 |
| `cost-approval` | by failure | M600 (S090) |
| `elicitation` | **by design** | M600 (S090 trail) |
| `goal-falsified` | by failure | dispatch; M600's vocabulary was missing it |

Blocking-by-design questions are schedulable in advance; blocking-by-failure ones are not.
That distinction is M600's and survives into the format as a derived property of `kind`,
not a hand-set field.

**Kind is a routing hint, never a gate.** `S062` measured 11 hand-authored `suspend_when`
clauses across two workflows: zero fired, and the one real suspension (`S061`) matched
none of them. The vocabulary was not wrong; *per-stage prediction of which kind would be
needed* was. So the format must not let anything reject a question for carrying the wrong
kind, and no stage pre-declares its kind.

## A request to another loop is the same object (D020)

Differing only in who answers, so it is a field, not a kind:

```
to ∈ denis | loop:<name> | check:<name>
```

D020's condition is explicit and watched: the justification holds *only while the request
path genuinely shares the question path*. If requests grow their own schema, routing, or
state, the decision inverts. Two obligations follow into the format:

- **A rejection is a reply.** A negative answer must carry enough to retry differently,
  escalate, or close as terminal. A silent no violates `S172`.
- **Broadcast is not a question** and does not close — explicitly a non-goal here.

## Seams found while exploring — reported to the visionary, not decided here

1. **Scope: format only, no `protocol/` code.** `CLAUDE.md`'s layout names the typed question
   (M600) as living in `src/yosefactory/protocol/`, but the dispatch grants me `questions/`
   and this change directory. Under Article IV I do not write `src/`. Delivered instead:
   the spec, the record schema as a documented shape, and example records under `questions/`.
   Reading and validating code is change 3's (`implement-turn-skill`) or a later dispatch's.
2. **YF-1's record shape did not exist when this was explored.** Their change was scaffolded
   (`.openspec.yaml` only) with no proposal. The two formats must share their record
   discipline — append-only, one JSON record per line, state as fold, RFC3339 UTC `ts`,
   `actor` — so this change states that discipline explicitly and cites it as the thing to
   reconcile. If YF-1's proposal lands divergent, this is the reconciliation list.
3. **`item` links the two formats.** A question names the backlog item it suspends; that
   field's exact name and id format belongs to YF-1's change and is assumed here.

## Acceptance test (from the dispatch)

Two branches suspend independently; answering one resumes exactly that one and leaves the
other suspended. At format level: two question files, an `answer` record echoing qid A →
fold(A) = answered, fold(B) = awaiting, and nothing in B's file changed.
