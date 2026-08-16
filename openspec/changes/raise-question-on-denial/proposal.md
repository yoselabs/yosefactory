# raise-question-on-denial

## Why

`_dispose`'s `blocked()` closure (`src/yosefactory/runtime/turn.py:429-452`) answers a permission
denial with one write: a turn-ledger row carrying `blocked_kind: needs_approval`. It never touches
the item. The item stays `doing` — not `blocked`, not `ready` — and `eligible()` admits only `ready`,
so no later turn ever looks at it again. The lease (`expires_at`) it was claimed under is never
checked by anything, so even a stale claim does not reclaim it.

`RESUMABLE` (`protocol/turn.py:119`) already names `needs_approval` as the kind that ought to be
recoverable, distinct from `refused` — D019's falsify-and-succeed dead-end-by-design. The distinction
is already drawn; nothing acts on it. A permission denial today produces a wait with no thing waited
on: no `deadline`, no `on_timeout`, no `return_to`, no correlation id an answer could name. S172 — every
loop must close — is violated at the point the loop is opened, not at the point it should have closed.

The format that would carry this already exists and is unused for it: `question.py`'s `asked` rule
and `backlog.py`'s `blocked` rule both require exactly the fields this case needs
(`deadline`, `on_timeout`, `return_to`, …), and a worked example of the near-identical shape
(`questions/examples/q-20260818T164500Z-d41c8e37.jsonl`, `kind: cost-approval`, `to: denis`) is
already checked in. Nothing in `src/` has ever written an `asked` record — zero non-test hits, grep-
confirmed. **This is not a new mechanism. It is the first production use of one that has been sitting
there**, fully specified and validated by test, unreached by any caller. See `exploration.md`.

## What Changes

- **A `NEEDS_APPROVAL` result raises a question and blocks the item**, instead of writing only a
  ledger row. Re-read against disk after `write-the-reason-fields` and the trailer change both
  landed: `_dispose`'s `blocked(detail, kind)` closure (`runtime/turn.py:466-478`) still only calls
  `_finish` — no item-log write for this branch — so the shape below still applies. Concretely, for
  `kind is BlockedKind.NEEDS_APPROVAL` specifically, before calling `_finish`:
  1. write `questions/<qid>.jsonl` with a single `asked` record: `item=<target.id>`,
     `kind=gate-failed` (a permission gate stopped the run and a human must clear it — distinct from
     `cost-approval`, reserved for an explicit spend ask the agent itself frames). **Checked, not
     assumed: `kind` has zero production readers today.** `blocking_by_design()`
     (`question.py:94`) is the only function that branches on it, and it has zero non-test callers —
     grep-confirmed, same as `asked` itself. With no consumer, the choice is documentation, so
     `gate-failed` stands; if a consumer is ever added, `kind` must be picked for *that* consumer's
     behaviour and this line re-argued then, not before — adding a member to the set for one caller
     is the rule-of-three trigger this fleet ratified today. `to=denis` (D005 — no other party holds
     approval rights over what runs),
     `text=<the executor's own denial detail>`, `answer_type=choice`, `options=["yes","no"]`,
     `return_to=doing`, `deadline=now + question_deadline_hours`, `on_timeout=default:no` (fail
     closed — a lapsed approval ask must not become a silent grant).
  2. append `blocked` to the item's own log: `awaiting={kind:question, ref:<qid>, who:owner,
     since:now, return_to:doing, nudge_at:[]}`.
  3. call `_finish` exactly as today, with the question file added to `paths` alongside `item_path`
     (`touched`) — `_finish`'s own `commit(...)` call already threads `run_id` through
     `_with_platform_trailers` (landed since this was explored), so the question file rides the same
     commit and inherits the platform trailer for free. No new commit call site, no new place to
     forget `run_id`.
- **`blocked()` stays a closure beside `failed()`, same signature style** — the file has three
  workers' worth of convergence on that shape (`_check_reason`/`_read_reason` shared, no new
  abstraction); this adds a branch inside it for one `BlockedKind`, not a new function shape.
- **A new guardrail, `question_deadline_hours`**, added to `runtime/config.py::DEFAULTS` beside
  `window`/`wall_clock_seconds`/`turn_ceiling`/`grace_seconds` — a required int with a default, not
  `_OPTIONAL` like the new `cost_ceiling_usd`: a question's `deadline` is a required field in the
  format (`question.py`'s `asked` rule), so unlike the cost ceiling there is no "send no value" state
  to represent. Same posture as its four DEFAULTS siblings: a guess, not a design commitment — "there
  is no traffic yet to choose it from" — so a conservative default (24h) and a config knob rather than
  a hard-coded constant.
- **`apply_answers` needs no change.** It already reads `questions/*.jsonl`, resolves `outcome()`,
  and unblocks the item via `return_to` — this proposal gives it its first real question to resolve
  for this path; the resolution machinery is already correct, only unfed.

## Non-goals

- **No tool name in the question text.** `stream.py::classify` currently reduces
  `permission_denials` to a boolean (`if event.get("permission_denials"):`) and never reads which
  tool was denied. A question whose text says only "the agent was denied a tool it asked for" is
  weaker than it could be, but fixing that is a `stream.py` change with its own scope (reading a list
  field, deciding what to do with more than one denial in one turn) and is not required for the loop
  to close. Recorded so a successor does not have to re-find it.
- **No sweeper.** This proposal writes a question with a real deadline; nothing yet closes it when
  the deadline passes. That is the separate, larger gap `exploration.md` names for Loop 2 and for
  whoever builds the sweeper — out of scope here on purpose. Until it exists, an unanswered approval
  question simply stays `awaiting` past its deadline, which is a known and named gap, not a silent one.
- **No `refused` handling.** `RESUMABLE` deliberately excludes it (D019); this proposal does not
  touch the `refused` branch of `blocked()`.

## Capabilities

### Modified Capabilities
- `turn-cycle`: a permission denial is added as a case that suspends the item on a question, rather
  than only narrowing to a ledger-row reason.

### New Capabilities
None — the question and backlog-item formats already declare everything this needs.

## Impact

- **`src/yosefactory/runtime/turn.py`** — the `blocked()` closure in `_dispose`, and the item-side
  `NEEDS_APPROVAL` branch specifically (the `REFUSED` branch is untouched).
- **`src/yosefactory/runtime/config.py`** — one new guardrail field with a default.
- **Sequencing**: `runtime/turn.py` and `runtime/config.py` are released to this proposal — YF-5's
  trailer change and YF-6's cost-ceiling change have both landed and the tree is clean. `write-the-
  reason-fields` and `wire-the-cost-ceiling` are both in, so `blocked_kind`, `_finish`'s trailer
  commit, and `cost_ceiling_usd` are all read from disk as they now are, not as explored earlier in
  this session.
- **No live receipt.** No test in this repository drives `take_turn` against a real executor — every
  one calls `claude.run()` in isolation. This change's coverage will be a wiring receipt (item ends
  `blocked`, a question file exists, `awaiting.ref` matches its `qid`) and not a live one (a real
  denial producing a real question row on disk). State that plainly at close; a green `make check`
  here proves the wiring, not the executor path.
