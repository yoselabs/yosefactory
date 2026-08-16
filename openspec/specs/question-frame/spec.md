# question-frame Specification

## Purpose
The durable, on-disk form of a typed question a suspended branch writes, and of the answer that
resumes exactly that branch — so an unattended run that meets something it cannot decide can put
the question somewhere that survives the process, and a sibling branch keeps running.
## Requirements
### Requirement: One append-only record log per question

Every question SHALL be stored as its own file under `questions/`, containing one JSON object
per line, appended in the order the records were written. A record, once written, SHALL NOT be
rewritten, reordered, or deleted (D002).

The first line of the file SHALL be an `asked` record. Subsequent lines MAY be `nudged`,
`answered`, `timed_out`, `cancelled`, or `noted` records.

Every record SHALL carry `event` (the event name), `event_id` (unique per event, the key
duplicate delivery is collapsed on), `ts` (RFC3339 timestamp in UTC), `actor` (who wrote the
record), and `qid` (the correlation id). The first four are the shared fold's required fields;
`qid` is this format's addition.

#### Scenario: A question is asked
- **WHEN** a branch suspends on a question
- **THEN** a new file `questions/<qid>.jsonl` exists whose single line is an `asked` record
- **AND** that record carries `qid`, `ts`, `actor`, `kind`, and the question text

#### Scenario: Concurrent suspensions do not contend
- **WHEN** two branches suspend at the same time in the same working tree
- **THEN** each writes a different file under `questions/`
- **AND** neither write modifies any line the other wrote

#### Scenario: History is never rewritten
- **WHEN** a question is answered
- **THEN** the `asked` record is still present, byte-identical, in the same file
- **AND** the answer is an additional line rather than an edit

### Requirement: A correlation id that the answer echoes

Every question SHALL carry a correlation id, `qid`, that is unique without coordination between
writers and is the stem of its own filename. Every record in that file SHALL repeat it.

An answer SHALL identify its question by `qid`. An answer whose `qid` matches no existing
question SHALL be rejected as an orphan and SHALL NOT close any other question.

Resolving one question SHALL NOT change the state of any other question.

#### Scenario: Answering one branch leaves its sibling suspended
- **WHEN** two questions A and B are both awaiting, and an `answered` record echoing A's `qid` is
  appended
- **THEN** A folds to `answered`
- **AND** B folds to `awaiting`, with its file unchanged

#### Scenario: An answer that names no question
- **WHEN** an `answered` record carries a `qid` with no corresponding file under `questions/`
- **THEN** it is treated as an orphan and no question changes state

#### Scenario: Ids do not collide across concurrent writers
- **WHEN** two branches in the same tree each mint a `qid` without consulting the other
- **THEN** the two ids differ

### Requirement: State is the fold of the log

A question's state SHALL be derived by folding its records in `(ts, event_id)` order and SHALL
NOT be stored as a mutable field. The states are `awaiting`, `answered`, `timed_out`, and
`cancelled`. Ordering SHALL NOT depend on position in the file, because a merge may interleave
appended lines.

A question is `awaiting` until it reaches a state in the terminal set (`answered`, `timed_out`,
`cancelled`). `terminal` SHALL be a derived predicate over that set, never a state and never a
written field.

Records SHALL be de-duplicated on `event_id`: a repeated `event_id` carrying identical content is
one event, and a repeated `event_id` carrying different content SHALL fail the read rather than
silently pick one.

#### Scenario: Duplicate delivery is safe
- **WHEN** the same `answered` record, with the same `event_id`, is appended twice
- **THEN** the question folds to `answered` exactly as if it appeared once

#### Scenario: One id, two contents
- **WHEN** two records share an `event_id` but differ in payload
- **THEN** the read fails, naming both lines, rather than resolving the disagreement silently

### Requirement: The format is a declaration over the shared fold

The question format SHALL be expressible as a declaration of the form `states`, `terminal_set`,
and `events: {name: one or more (from_states, to_state, required_payload_keys) rules}`, and SHALL
be read by the same generic fold that reads backlog items. There SHALL NOT be a question-specific
parser (D020: a request, a question, and an item are one object in different states).

An event MAY declare more than one rule. The rules for an event SHALL be ordered, and the first
rule whose `from_states` matches the current state SHALL be the one applied — its target, its
required payload keys, and its patterns. Rules for one event MAY therefore differ in what they
require, because what a record must carry depends on what it is doing. This adds no vocabulary: an
event with several legal shapes depending on the state it arrives in is what a transition table
already expresses.

`from_states` SHALL be able to name terminal states explicitly. A state being terminal SHALL NOT
by itself make an event illegal; an event is illegal exactly when **no** rule declared for it
matches the current state.

`terminal` SHALL be a derived predicate over `terminal_set`, never a state and never a written
field.

An event for which no declared rule matches the current state SHALL fail the read, loudly and with
the line named. A reader that skips what it does not understand reports a state that never
existed.

The governing rule for what the declaration tolerates is:

> **Reject what could only come from a bug. Absorb what a correct actor could legitimately have
> written — and declare each such case explicitly.**

The discriminator SHALL be *could a correct actor have written this*, and SHALL NOT be *is the
target terminal*. Absorption SHALL be declared case by case as a rule; there SHALL NOT be a
general tolerance for events arriving after closure. The test that separates the two cases is
whether the writing actor could have avoided the race: a timer-driven writer reads the log and
appends as two steps and cannot make them one, so a close it appends a second after another close
is not evidence of a defect. A writer that decides deliberately has read the log it is closing,
so a second deliberate close is.

De-duplication on `event_id` is what makes at-least-once delivery safe, so tolerance SHALL NOT be
used for it: a retried close carries the same `event_id` and is applied once. A second close
carrying a *different* `event_id` is therefore not a retry, and SHALL fail the read unless a rule
declares that case absorbed.

The declaration is:

- `initial`: `asked`
- `states`: `awaiting`, `answered`, `timed_out`, `cancelled`
- `terminal`: `answered`, `timed_out`, `cancelled`
- `rules`:
  - `asked`: (nothing) → `awaiting`, requiring `item`, `kind`, `to`, `text`, `answer_type`,
    `return_to`, `deadline`, `on_timeout`; `kind` and `on_timeout` pattern-checked
  - `nudged`: `awaiting` → no state change, requiring `reason`
  - `noted`: any state → no state change, requiring `body` — a note never changes a state and
    stays legal after a question has closed, matching the item declaration
  - `answered`: `awaiting` → `answered`, requiring `verdict`, `answer`
  - `timed_out`: two rules, in this order —
    1. `awaiting` → `timed_out`, requiring `policy`, `answer`
    2. any terminal state → no state change, requiring nothing: the question was already closed
       when the sweeper's record landed, so the record is retained and changes nothing
  - `cancelled`: `awaiting` → `cancelled`, requiring `reason`

`answered` and `cancelled` SHALL remain legal only from `awaiting`. A writer of either SHALL read
the log before appending.

#### Scenario: A late timeout is absorbed rather than failing the read

- **WHEN** a question is answered at T, and a sweeper appends a `timed_out` record at T+1s because
  it read the log before the answer landed
- **THEN** the read succeeds and the question folds to `answered`
- **AND** the `timed_out` record is retained in the log and visible in the question's records
- **AND** no state change is attributed to it

#### Scenario: A second terminal event

- **WHEN** a deliberate terminal record — an `answered`, or a `cancelled` — carrying a different
  `event_id` is appended to an already-`answered` question
- **THEN** the read fails, naming the line and the illegal transition
- **AND** this holds for every terminal event except those a rule declares absorbed, which today
  is `timed_out` alone

#### Scenario: Absorption is declared, not general

- **WHEN** an event with no rule matching a terminal state is appended to a closed question
- **THEN** the read fails, rather than being tolerated because the question was closed

#### Scenario: The first matching rule wins

- **WHEN** `timed_out` is appended to an `awaiting` question
- **THEN** the first rule applies, the question folds to `timed_out`, and the record is required to
  carry `policy` and `answer`

#### Scenario: One fold, two declarations

- **WHEN** the generic fold reads a question log and a backlog item log
- **THEN** it branches on neither, taking the difference entirely from the declaration

### Requirement: A closed set of question kinds, used only for routing

Every `asked` record SHALL carry `kind`, one of: `decision`, `ambiguity`, `out-of-depth`,
`gate-failed`, `cost-approval`, `skip-the-skill`, `elicitation`, `goal-falsified`.

`kind` SHALL be advisory — it routes and prioritises a question and MAY determine who is asked.
Nothing SHALL refuse, discard, or defer a question on the grounds that its kind is wrong for the
stage that emitted it, and no stage SHALL be required to declare in advance which kinds it may
emit. (S062: eleven hand-authored suspension clauses, zero fired, and the one real suspension
matched none of them — the vocabulary held, the per-stage prediction did not.)

A question MAY be emitted by the system rather than requested by a stage. `skip-the-skill` — the
offer to abandon a skill when frustration is detected (S090) — is the first such kind, and it
needs no separate machinery precisely because kind routes rather than gates: a question nothing
predicted is stored and answered like any other.

`elicitation` SHALL be marked blocking-by-design; the other seven SHALL be marked
blocking-by-failure. This property is derived from `kind` and SHALL NOT be set independently.

#### Scenario: An unexpected kind from a stage
- **WHEN** a stage emits a `goal-falsified` question and nothing predicted that it would
- **THEN** the question is stored and awaits an answer exactly as any other kind does

#### Scenario: A kind outside the closed set
- **WHEN** an `asked` record carries a `kind` not in the closed set
- **THEN** the record is invalid and the question is not considered well-formed

#### Scenario: A question nobody asked for
- **WHEN** the system itself emits a `skip-the-skill` question, with no stage having requested it
- **THEN** it is stored, routed, and answered exactly as a stage-requested question is

### Requirement: Every question carries its own closure

Every `asked` record SHALL carry a `deadline` and an `on_timeout` policy, one of:

- `escalate` — re-ask, upward, of a party who can answer
- `default:<answer>` — an answer **pre-registered at ask time**
- `abandon:<reason>` — close as terminal without an answer

The question SHALL be the single owner of these two fields **wherever a question exists**. A backlog
item suspended on a question SHALL NOT repeat them; it names the question and reads them from it. An
item blocked on another item has no question, so nothing there is duplicated and that block carries
its own bound — see `backlog-item-format`.

A `default:` policy SHALL name an answer that would be legal for this question at the moment it
is asked; an `on_timeout` naming an illegal answer SHALL make the record invalid. The default
SHALL NOT be chosen, edited, or supplied after the question has been asked.

Once the deadline has passed and no terminal record exists, a sweeper SHALL append a `timed_out`
record carrying the policy's outcome, so that the loop closes the question itself (S172).

#### Scenario: A pre-registered default fires

- **WHEN** a question with `on_timeout: default:<answer>` reaches its deadline unanswered
- **THEN** a `timed_out` record is appended carrying that pre-registered answer
- **AND** the question folds to `timed_out` with the default as its outcome

#### Scenario: A default supplied late

- **WHEN** a `default:` value is written into a question after its `asked` record
- **THEN** the record is invalid, because the default was not pre-registered

#### Scenario: No open loop survives its deadline

- **WHEN** any question's deadline has passed
- **THEN** it holds a terminal record, or a sweeper is obliged to append one

#### Scenario: A question that could never close

- **WHEN** an `asked` record omits `deadline` or `on_timeout`
- **THEN** the read of that question fails, rather than yielding a question that awaits forever
- **AND** S172 therefore cannot be expressed wrongly, not merely detected after the fact

#### Scenario: The suspended item does not hold a second copy

- **WHEN** an item is suspended on a question and the question's `deadline` is read
- **THEN** it is read from the question, and the item's own record carries no `deadline` to
  disagree with it

### Requirement: Wake on a timer or on activity, whichever comes first

A question SHALL be resolvable at any time before its deadline, and an answer arriving early
SHALL take effect immediately rather than waiting for the deadline.

A sweeper SHOULD read the log and append `timed_out` only when the question holds no terminal
record. Because reading and appending are two steps, a sweeper MAY nonetheless append `timed_out`
to a question that closed in between, and the format SHALL absorb that record rather than failing
the read: the question keeps the state it already reached, and the late record is retained. The
no-op is therefore a property of the declaration and not an obligation on the writer.

`nudge_at` MAY carry reminder times. A reminder SHALL be recorded as a `nudged` record and SHALL
NOT change the question's state.

#### Scenario: An early answer pre-empts the deadline

- **WHEN** a question is answered before its deadline and the sweeper later runs and appends
  nothing
- **THEN** the state stays `answered`

#### Scenario: The sweeper loses the race and nothing needs repair

- **WHEN** a sweeper appends `timed_out` to a question answered one second earlier
- **THEN** the state stays `answered`, the read succeeds, and no human repair is required

#### Scenario: A reminder is an event, not a state

- **WHEN** a `nudged` record is appended to an awaiting question
- **THEN** the question is still `awaiting` and its deadline is unchanged

### Requirement: The resume target is stored, not recomputed

Every `asked` record SHALL carry `return_to`: the state the asking branch resumes into once
answered, decided and written down at suspension time. It SHALL NOT be inferred later.

An `asked` record MAY carry `resume_ref`, an opaque token belonging to whatever harness
suspended the branch, and `context`, the state an answerer needs in order to answer. A reader of
this format SHALL NOT interpret `resume_ref`.

#### Scenario: Resuming after an answer
- **WHEN** a question is answered
- **THEN** the branch resumes at the `return_to` recorded when it suspended

#### Scenario: The harness changes
- **WHEN** the value or shape of `resume_ref` changes
- **THEN** previously written questions remain readable and their states unchanged

### Requirement: A request to another loop is the same object

Every `asked` record SHALL carry `to`, naming who owes the answer: `denis`, `loop:<name>`, or
`check:<name>`. A request made of another loop SHALL differ from a question asked of the
operator only in this field — not in schema, storage, routing, or lifecycle (D020).

A negative answer SHALL carry a structured cause and SHALL state whether the asker may retry
differently, escalate, or must close as terminal. An answer that conveys only refusal SHALL be
invalid.

One-to-many notifications with no expected reply are NOT questions and SHALL NOT be stored in
this format.

#### Scenario: A cross-loop request
- **WHEN** one loop needs a change in a repository another loop owns
- **THEN** it writes an ordinary question with `to: loop:<name>` and continues other work

#### Scenario: A rejection that leaves somewhere to go
- **WHEN** an answer rejects the request
- **THEN** it carries a cause and one of retry, escalate, or terminal

#### Scenario: A broadcast is not stored here
- **WHEN** a loop announces something no one must answer
- **THEN** no question file is created

### Requirement: Record discipline shared with the backlog format

Questions and backlog items SHALL share their storage discipline: append-only files, one JSON
record per line, state derived by folding, `ts` as RFC3339 UTC, and an `actor` on every record.

An `asked` record SHALL name the backlog `item` whose work it suspends, so that a suspended item
and its open question are mutually discoverable.

#### Scenario: A suspended item and its question find each other
- **WHEN** an item is suspended on a question
- **THEN** the question names the item, and the item's own trail names the `qid`

#### Scenario: One reading discipline
- **WHEN** a reader folds either a question log or a backlog item log
- **THEN** the same rules apply, and the same fold runs: append-only, one record per line,
  `(ts, event_id)` order, dedup on `event_id`, and an illegal transition fails the read

