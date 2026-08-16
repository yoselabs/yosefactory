## Context

See `proposal.md` — Why. Two constraints shape everything below.

**The tree is shared and writers are invisible to each other.** Several workers and, later,
several branches of one run write into one working tree with no locking. `architecture.md` §4
settles the mechanism: append-only, one record per line, state derived by folding at read time.

**The suspend/resume half already exists; the store does not.** S099 measured ~25 systems:
`permissionDecision: "defer"` ends a query and resumes it from the persisted session, and
`session_store` / `resume` / `fork_session` supply durability — but no production system lets an
agent spontaneously emit a typed question to a durable location and die. The durable location is
ours to define, and it must not assume the harness that wrote it will be the harness that reads
it.

## Goals / Non-Goals

**Goals:**
- A question is legible, foldable, and answerable with no running process and no index.
- Concurrent suspensions never contend; concurrent answers never corrupt.
- The acceptance test — answer one of two suspended branches, the other stays suspended — is a
  property of the format, not of a runtime.

**Non-Goals (design level; `proposal.md` carries the scope-level ones):**
- No index, no manifest, no `questions/state.json`. Any derived view is rebuildable by reading
  the directory, and a second master is exactly the failure `architecture.md` §7 names.
- No schema version negotiation. A `v` field is carried; migration policy is deferred.
- No prescription of *how* a sweeper is scheduled, only what it may append and when.

## Decisions

### One file per question, not one shared log

Alternatives: a single `questions/log.jsonl`; a question directory per item; git notes with
`cat_sort_uniq` (git-appraise's shape).

Chosen because the concurrency story is then trivially true rather than argued: two branches
suspending write two different paths, so there is nothing to merge. A shared log makes every
concurrent suspension a same-region append — the case git resolves worst — and buys only a
cheaper directory listing. Git notes are the more sophisticated answer and cost a mechanism
nobody in this repo has used yet; the trade is deferred, not rejected, and the per-file format
is what would be stored in notes anyway.

Consequence accepted: a question's records live in one file that both the asker and the answerer
append to. Those two appends can race, but they are seconds apart at worst and both are line
appends, so the resolution is a sort by `ts`. This is the only merge in the design.

### The correlation id is the filename stem

Format: `q-<YYYYMMDD>T<HHMMSS>Z-<8 hex>`, e.g. `q-20260816T171204Z-3f9a2c1d`.

Alternatives: a UUIDv4; a monotonic counter; a content hash.

Chosen because it is unique without coordination (the random suffix), sorts chronologically in a
plain `ls` (the timestamp prefix), is a legal filename on every platform in play, and survives
being pasted into a chat message or a board comment by a human — which is how answers will
actually arrive at first. A counter needs a coordinating writer, which Article III forbids in
practice. A content hash hides the ordering that makes a directory listing useful.

The id being the path means an answer's target is resolvable by string concatenation. No lookup,
no index, nothing to fall out of date.

### State is folded, never stored; first terminal record wins

Alternatives: a `status` field rewritten in place; a status file beside the log.

Rewriting is the thing `architecture.md` §4 rules out. The tie-break rule — first terminal
record by `ts` decides, later ones are retained and ignored — is what makes the fold total: a
duplicate answer, an answer that races the sweeper's timeout, and a replayed board event all
produce the same state from the same bytes. Deterministic replay is the same property
`architecture.md` §7 requires of board event consumption, obtained here for free.

`ts` ties are broken by the order of lines in the file, which is the order they were appended.

### The record shapes

```json
{"rec":"asked","v":1,"qid":"q-20260816T171204Z-3f9a2c1d","ts":"2026-08-16T17:12:04Z",
 "actor":"loop:yosefactory/turn","item":"i-20260816-0007","kind":"cost-approval",
 "to":"denis","text":"Spend ~$4 rerunning the extraction with a larger context?",
 "answer_type":"choice","options":["yes","no"],
 "context":{"est_usd":4.0,"prior_attempts":2},
 "return_to":"act","resume_ref":{"session_id":"…","message_id":"…"},
 "nudge_at":["2026-08-19T09:00:00Z","2026-08-23T09:00:00Z"],
 "deadline":"2026-08-23T17:00:00Z","on_timeout":"default:no"}
```

```json
{"rec":"answer","v":1,"qid":"q-20260816T171204Z-3f9a2c1d","ts":"2026-08-16T21:40:11Z",
 "actor":"denis","verdict":"accept","answer":"yes","event_id":"gh-issue-14-comment-3"}
```

```json
{"rec":"answer","v":1,"qid":"q-20260816T171331Z-b7e40a52","ts":"2026-08-17T08:02:00Z",
 "actor":"loop:shelf","verdict":"reject","cause":"promotion needs a third consumer",
 "next":"retry","answer":"open a promotion request after the third caller exists"}
```

```json
{"rec":"timeout","v":1,"qid":"q-20260816T171204Z-3f9a2c1d","ts":"2026-08-23T17:00:03Z",
 "actor":"loop:yosefactory/sweeper","policy":"default:no","answer":"no"}
```

`nudge`, `cancel`, and `note` carry the common four fields plus a `reason` or `body`.

`answer_type ∈ text | choice | bool`, with `options` required for `choice`. This exists for one
reason: `on_timeout: default:<answer>` must be checkable against the question at ask time, and
"is this a legal answer" needs a stated answer space. It is deliberately the smallest typing
that makes the pre-registration rule enforceable.

`verdict ∈ accept | reject`, and `reject` requires `cause` plus `next ∈ retry | escalate |
terminal`. This is D020's "a rejection is a reply" made structural rather than hoped for —
Denis's objection to pull requests was precisely that a *no* leaves the requester nowhere to go.

### Kind is advisory, and the format says so out loud

The natural implementation of a closed vocabulary is validation that rejects anything else. S062
is the argument against going further than that: eleven `suspend_when` clauses were
hand-authored from M600's own vocabulary, none fired, and the one real suspension matched none.
The vocabulary survived; predicting *where* each kind arises did not. So the format validates
membership in the set and forbids anything downstream from refusing a question because its kind
was unexpected. Encoding a measured failure is cheaper than repeating it.

### `to` is a field, not a subtype

D020 chose the request channel because a request and a question are one object differing only in
who answers, which made the cheap option and the correct option the same option. That argument
is conditional: it holds only while the paths genuinely stay shared. Making `to` a field rather
than a second record kind is what keeps the condition true by construction — a request cannot
grow its own schema without visibly editing this spec.

## Risks / Trade-offs

- **Two writers appending to one question file collide** → the only merge in the design;
  resolution is sort-by-`ts`, and the fold is order-insensitive apart from the first-terminal
  rule, so a mis-ordered merge cannot change state.
- **A directory of thousands of files gets slow to fold** → not a concern at one operator's
  volume; if it becomes one, the answer is git notes or a derived index that is rebuilt from the
  directory, never authoritative.
- **`resume_ref` is harness-shaped and this repo has one harness** → it is opaque and readers
  are forbidden to interpret it, so a harness change invalidates resumability of *in-flight*
  questions only, not the readability or comparability of the record. That is the split
  `CLAUDE.md`'s structural rule asks for.
- **Nothing executable validates these rules in this change** → deliberate; scope is
  `questions/` (Article IV). Until a validator exists, "invalid record" is a documented rule a
  reader must apply, and the first consumer (change 3) is where it becomes enforced. Flagged to
  the director rather than absorbed.
- **The pre-registered default is the field most likely to be skipped in practice** → a question
  written without a deadline and policy is invalid rather than merely incomplete, so the
  omission fails loudly at the point of writing rather than silently at the point of never being
  answered. Starvation is the failure `architecture.md` §5 names as the one that bites.
- **`item` is assumed** → the backlog format is being written concurrently by another worker
  (YF-1). If their id shape differs, this is a rename in examples and one line in the spec.

## Migration Plan

Nothing to migrate: no questions exist. `questions/` is created by this change with a `README.md`
stating the format and one worked pair of example files. Rollback is deleting the directory,
which is safe only while it holds no real questions — after the first real suspension, D002
applies and the directory is append-only like the ledger.

## Open Questions

- **Where the schema becomes executable.** `CLAUDE.md` places the typed question in
  `src/yosefactory/protocol/`; this change is scoped to `questions/`. Whether the validator lands
  in `protocol/` as its own dispatch or inside change 3 is the director's call and changes no
  requirement here.
- **Whether `bd` ends up managing these files.** Q433 is open; the format is files in a
  directory either way.
- **Schema versioning policy.** `v: 1` is carried so the question is answerable later; nothing in
  the current design depends on the answer.
