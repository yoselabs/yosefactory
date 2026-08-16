## Why

A branch that meets something it cannot decide has nowhere durable to put the question, so an
unattended run must guess or die (M600; S983's measured gap). The harness already supplies the
suspend and the resume — `permissionDecision: "defer"`, `session_store`, `resume`,
`fork_session` — and S099's sweep of ~25 systems found that the one part nobody ships is the
durable question store. That store is a format, and this change is it.

Promotion: **M600** (suspend-and-resume with a typed question), with **D020** (a cross-repo
request is the same object as a question), **S099** (branch-level halting is correlation-id
based), **S075** (a question stands; only its timing moves), **S172** (every loop must close),
and `architecture.md` §5.

Now, because change 3 (`implement-turn-skill`) consumes this format, and because a format
decided while writing the consumer is a format shaped by one caller.

## What Changes

- **New: `questions/`** — one file per question, append-only, one JSON record per line. The
  filename stem is the correlation id.
- **A correlation id every answer echoes.** Answering one question resumes exactly the branch
  that asked it and leaves sibling branches suspended. Anything that suspends "the run" as a
  unit is rejected by construction (S099).
- **State is the fold of the record log, never a stored field** (`architecture.md` §4). First
  terminal record wins; later ones are retained and ignored, which makes duplicate delivery
  safe.
- **Seven question kinds** — `decision`, `ambiguity`, `out-of-depth`, `gate-failed`,
  `cost-approval`, `elicitation`, `goal-falsified`. The last is new; M600's vocabulary was
  missing it. Kind is a routing hint that nothing may reject a question for carrying, and no
  stage pre-declares which kind it will emit (S062: 11 hand-authored `suspend_when` clauses,
  zero fired, the one real suspension matched none).
- **`deadline` + `on_timeout ∈ escalate | default:<answer> | abandon:<reason>`**, the default
  answer pre-registered at ask time and required to be a legal answer to that question. On
  expiry the loop closes the question itself, making S172 self-enforcing rather than
  aspirational.
- **Wake on timer OR new activity, whichever comes first**, expressed as a property of the fold
  rather than a scheduler feature: the sweeper appends `timeout` only when no terminal record
  exists past the deadline, so an early answer makes it a no-op.
- **`return_to` stored at ask time, not recomputed** (`architecture.md` §5).
- **A request to another loop is the same object as a question** (D020) — `to ∈ denis |
  loop:<name> | check:<name>`. Who answers is a field, not a second design. A rejection is a
  reply and must carry enough to retry differently, escalate, or close as terminal.

## Capabilities

### New Capabilities
- `question-frame`: the durable typed question a suspended branch writes — its record schema,
  correlation id, kinds, fold rules, and the answer/timeout/cancel records that close it.

### Modified Capabilities
<!-- None. No existing specs under openspec/specs/. -->

## How the acceptance criterion is verified

**By inspection and by borrowed execution — not by `make check`.** This change ships worked
fixtures and a declaration; it ships no code of its own, so nothing in CI fails if a record is
malformed. The four fixtures were run through the shared fold (`protocol/eventlog.py`) from a
scratch script: the two-branch test passes, and the illegal-transition case fails loudly as it
should. What is missing is a committed declaration and a test under `make check`, which the
director sequences after the fold lands.

The format is written as a **declaration** for that shared fold (`states`, `terminal_set`,
`events: {name: (from_states, to_state, required_payload_keys)}`), so it runs on the generic
parser unchanged rather than needing a second one. D020 makes a request, a question, and an item
one object in different states; one fold is the consequence.

## Non-goals

- **No `src/` code, no validator, no reader library.** The dispatch scopes this worker to
  `questions/` and this change directory (`orchestration.md` Article IV). `CLAUDE.md` places
  the typed question in `src/yosefactory/protocol/`; putting it there is a later dispatch's
  work and is flagged, not silently absorbed.
- **No broadcast.** *"Five packages got updated"* is one-to-many with no reply expected; D020
  states it is not an unclosed loop because nothing waits on it. Modelling it here would break
  the invariant's checkability.
- **No board integration, no steering inbox, no sweeper implementation.** This change says what
  a sweeper must append and when it may; changes 4 and 6 build the things that append.
- **No answer-routing or notification policy.** Who gets told a question is pending is the
  board adapter's job (`architecture.md` §7).
- **No role model.** M600 is explicit: the primitive is the question and the resume; who
  answers is a field. At N=1 all parties are the operator.
- **Does not settle whether `bd` manages these files.** Q433 is open and stays open.

## Impact

- **New directory `questions/`** with example records and a `README.md` stating the format.
- **Consumed by** change 3 (`implement-turn-skill`), change 4 (`implement-steering-inbox`,
  which writes `answer` records), and the sweeper in change 6.
- **Shares record discipline with** `define-backlog-frame-format` (YF-1, concurrent):
  append-only, one JSON record per line, state as fold, RFC3339 UTC `ts`, `actor`. A question
  names the backlog `item` it suspends; that id format is YF-1's to define and is assumed here.
- **No dependencies added.** No source, no tests, no `make check` surface — this change is data
  and its stated rules.
- **Repository is public**: examples carry no client names and no former-employer references.
