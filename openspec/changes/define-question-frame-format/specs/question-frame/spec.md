## Purpose

The durable, on-disk form of a typed question a suspended branch writes, and of the answer that
resumes exactly that branch — so an unattended run that meets something it cannot decide can put
the question somewhere that survives the process, and a sibling branch keeps running.

## ADDED Requirements

### Requirement: One append-only record log per question

Every question SHALL be stored as its own file under `questions/`, containing one JSON object
per line, appended in the order the records were written. A record, once written, SHALL NOT be
rewritten, reordered, or deleted (D002).

The first line of the file SHALL be an `asked` record. Subsequent lines MAY be `nudge`,
`answer`, `timeout`, `cancel`, or `note` records.

Every record SHALL carry `rec` (the record kind), `qid` (the correlation id), `ts` (RFC3339
timestamp in UTC), and `actor` (who wrote the record).

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
- **WHEN** two questions A and B are both awaiting, and an `answer` record echoing A's `qid` is
  appended
- **THEN** A folds to `answered`
- **AND** B folds to `awaiting`, with its file unchanged

#### Scenario: An answer that names no question
- **WHEN** an `answer` record carries a `qid` with no corresponding file under `questions/`
- **THEN** it is treated as an orphan and no question changes state

#### Scenario: Ids do not collide across concurrent writers
- **WHEN** two branches in the same tree each mint a `qid` without consulting the other
- **THEN** the two ids differ

### Requirement: State is the fold of the log

A question's state SHALL be derived by folding its records in timestamp order and SHALL NOT be
stored as a mutable field. The states are `awaiting`, `answered`, `timed_out`, and `cancelled`.

A question is `awaiting` until it holds a terminal record. `answer`, `timeout`, and `cancel` are
terminal. The **first** terminal record determines the state; later terminal records SHALL be
retained and SHALL NOT change it.

#### Scenario: Duplicate delivery is safe
- **WHEN** the same `answer` is appended twice
- **THEN** the question's state is `answered` and its answer is the one from the first record

#### Scenario: An answer racing a timeout
- **WHEN** both an `answer` and a `timeout` record exist for one question
- **THEN** the earlier record by `ts` determines the state, and the later one is retained as
  history

### Requirement: A closed set of question kinds, used only for routing

Every `asked` record SHALL carry `kind`, one of: `decision`, `ambiguity`, `out-of-depth`,
`gate-failed`, `cost-approval`, `elicitation`, `goal-falsified`.

`kind` SHALL be advisory — it routes and prioritises a question and MAY determine who is asked.
Nothing SHALL refuse, discard, or defer a question on the grounds that its kind is wrong for the
stage that emitted it, and no stage SHALL be required to declare in advance which kinds it may
emit. (S062: eleven hand-authored suspension clauses, zero fired, and the one real suspension
matched none of them — the vocabulary held, the per-stage prediction did not.)

`elicitation` SHALL be marked blocking-by-design; the other six SHALL be marked
blocking-by-failure. This property is derived from `kind` and SHALL NOT be set independently.

#### Scenario: An unexpected kind from a stage
- **WHEN** a stage emits a `goal-falsified` question and nothing predicted that it would
- **THEN** the question is stored and awaits an answer exactly as any other kind does

#### Scenario: A kind outside the closed set
- **WHEN** an `asked` record carries a `kind` not in the closed set
- **THEN** the record is invalid and the question is not considered well-formed

### Requirement: Every question carries its own closure

Every `asked` record SHALL carry a `deadline` and an `on_timeout` policy, one of:

- `escalate` — re-ask, upward, of a party who can answer
- `default:<answer>` — an answer **pre-registered at ask time**
- `abandon:<reason>` — close as terminal without an answer

A `default:` policy SHALL name an answer that would be legal for this question at the moment it
is asked; an `on_timeout` naming an illegal answer SHALL make the record invalid. The default
SHALL NOT be chosen, edited, or supplied after the question has been asked.

Once the deadline has passed and no terminal record exists, a sweeper SHALL append a `timeout`
record carrying the policy's outcome, so that the loop closes the question itself (S172).

#### Scenario: A pre-registered default fires
- **WHEN** a question with `on_timeout: default:<answer>` reaches its deadline unanswered
- **THEN** a `timeout` record is appended carrying that pre-registered answer
- **AND** the question folds to `timed_out` with the default as its outcome

#### Scenario: A default supplied late
- **WHEN** a `default:` value is written into a question after its `asked` record
- **THEN** the record is invalid, because the default was not pre-registered

#### Scenario: No open loop survives its deadline
- **WHEN** any question's deadline has passed
- **THEN** it holds a terminal record, or a sweeper is obliged to append one

### Requirement: Wake on a timer or on activity, whichever comes first

A question SHALL be resolvable at any time before its deadline, and an answer arriving early
SHALL take effect immediately rather than waiting for the deadline. A sweeper SHALL append a
`timeout` record only when the question holds no terminal record; encountering an
already-terminal question SHALL be a no-op.

`nudge_at` MAY carry reminder times. A reminder SHALL be recorded as a `nudge` record and SHALL
NOT change the question's state.

#### Scenario: An early answer pre-empts the deadline
- **WHEN** a question is answered before its deadline and the sweeper later runs
- **THEN** the sweeper appends nothing and the state stays `answered`

#### Scenario: A reminder is an event, not a state
- **WHEN** a `nudge` record is appended to an awaiting question
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
- **THEN** the same rules apply: append-only, one record per line, first terminal record wins
