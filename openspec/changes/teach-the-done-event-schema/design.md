## Context

Verified against disk before writing anything below (Article XII):

- `runtime/turn.py` line ~530: `invocation = Invocation(skill=skill, vocabulary=backlog.
  VOCABULARY_SPEC, proposal_path=proposal_path)` — the only construction site, unconditional
  whenever an agent runs (both the claimed-item and planning branches use the same `invocation`).
- `protocol/backlog.py`'s `ITEM.rules["done"]` requires `(("effects",), ("verified_by",))`, and
  `VOCABULARY_SPEC` resolves via `repo_root()` marker walk to `openspec/specs/backlog-item-format/
  spec.md`, whose table's `done` row reads `Carries: effects, verified_by` — already correct,
  already matching the code.
- `executor/invocation.py`'s `render()` currently emits, in order: the skill line, the vocabulary
  line ("The event vocabulary is defined at {path}."), the proposal-path line. This whole block is
  the *entire* user-turn prompt (`executor/claude.py::render()` joins only `frame` + this), sent
  once, at the very start of a `claude -p` invocation that then runs autonomously — reading code,
  editing, testing, committing — for as long as its budget allows, before writing the proposal.
- `workflows/turn-skill.md` (94 words, cap 120 per `test_the_skill_stays_short`, S098) says nothing
  about the vocabulary or required fields at all; it only describes the mechanics of the write
  (one JSON object, no `event_id`/`ts`/`actor`, don't touch `backlog/`).
- `tests/runtime/test_turn_integration.py`'s `test_a_real_agent_reaches_done_once_the_vocabulary_
  is_reachable` (`teach-event-vocabulary`'s receipt) is a **short** synthetic run —
  `test_command=("true",)`, a one-line-file task — and it passed: the agent read the pointer and
  wrote a legal `done`. `score-d014-against-a2web`'s turn 2 was a real, long, budget-constrained
  a2web feature (new test, real code, real `make check`) and it did not. The variable that changed
  between "the mechanism works" and "the mechanism failed" is turn length and distance-in-context
  between the pointer and the write action, not the pointer's existence or content.

## Goals / Non-Goals

**Goals:**
- Move the *reminder* to check required fields closer, in context, to the moment the agent writes
  its proposal — without adding a second definition of the schema anywhere.
- Make the reachability claim checkable at $0: prove, by running the real `take_turn` code path
  against a `FakeExecutor`, that the directive is actually present in what the agent receives.
- Make the content claim checkable at $0 and durable: a test that fails the moment `ITEM.rules`'
  required fields and `backlog-item-format/spec.md`'s documented `Carries` cells disagree, for any
  event, not just `done`.

**Non-Goals:** see `proposal.md`.

## Decisions

**Reword, don't extend, the `Invocation.render()` vocabulary line.**

```
old: "The event vocabulary is defined at {path}."
new: "The vocabulary at {path} names the required fields for whichever event you write —
      check it before you do."
```

Same position in `render()` (skill, vocabulary, proposal path — unchanged order, unchanged spec
scenario). The old line states a fact about the world ("a vocabulary exists, here is where"); the
new line states an instruction tied to the action the agent is about to take ("check it before you
write"). No field name enters the string — grep for `effects`/`verified_by`/`awaiting` in
`invocation.py` after this change still returns nothing, which the new drift/reachability tests
both assert.

**Add one clause to `turn-skill.md`, not zero.** `teach-event-vocabulary/design.md` chose to leave
`turn-skill.md` byte-for-byte unchanged and put the pointer entirely in `Invocation.render()`. That
was the right call for *reachability* (get the agent to the file at least once) and it worked in
the short receipt. It was not enough for *timing*: `turn-skill.md` is the text the agent is told to
"Follow" for the concrete mechanics of the write it is about to perform, which makes it — unlike
the invocation preamble, read once at the very start — plausibly reread by the agent at or near the
moment it acts, because that is literally what it describes. A skill instructing "write the JSON
object" gains a same-breath reminder to check the vocabulary first; the vocabulary's location was
already established earlier in the same prompt, so `turn-skill.md` refers to "the vocabulary"
without repeating its path. 111 words, 9 under the 120-word ceiling — the ceiling that stopped
inlining the *table* still applies and is not touched; a 17-word directive is not a 150-200-word
table.

**Why this counts as root-cause rather than a second patch on the same spot.** The dispatch warns
against "relaxing the gate" as the forbidden branch; this touches neither `verify.may_write_done`
nor `ITEM.rules`. But a narrower version of the same failure mode is possible here too: adding words
without changing what the agent actually does is cosmetic, not root-cause. The distinguishing claim
this design makes and the receipts below check: the failure was not "the agent doesn't know the
fact exists" (it does — the pointer was read successfully in the short receipt) but "the fact isn't
salient at the moment of the write, on a long run." Moving the reminder to the two spots nearest, in
context-order, to that moment is the mechanism-level fix for exactly that failure, not a wording
tweak that only reads better.

**Not adding a new `Invocation` field, not adding a second `Read`-forcing mechanism.** A tempting
alternative is to make the harness re-inject the vocabulary text immediately before the proposal
write (e.g., a second prompt turn). Rejected: `claude -p` here is a single non-interactive
invocation with no mid-run injection point in the pinned executor (`executor/claude.py`'s own
docstring: no turn ceiling, no mid-stream control). Building one would be new runtime machinery for
a problem two one-line text edits address; if the receipts below show the reworded/repositioned
text still isn't enough, that is the next change's finding, not something to build speculatively
now.

## Receipts

**1. Content cannot drift silently — `tests/protocol/test_backlog_fold.py`.**

Parses `backlog.VOCABULARY_SPEC`'s own markdown table (the file on disk, read at test time, not a
copy pasted into the test) and asserts, for every event in `backlog.ITEM.rules`, that the rule's
required top-level field names are a subset of that event's documented `Carries` cell. Subset, not
equality, because the table already documents some non-required context (`unblocked`'s `ref` is
listed but not enforced, pre-existing and correct) — the property that matters is that the *fold
never requires more than the table promises*, which is exactly the shape of gap that bit `done`
originally (before `teach-event-vocabulary`) and would bite silently again if a future change
tightened a rule without touching the doc. This is the "spec and instruction cannot drift" receipt
the dispatch asked for, and it is stronger than `teach-event-vocabulary`'s own coverage: that
change proved the pointer resolves to an existing file; this proves the file's content stays true
to the code, for all eighteen events, automatically, on every `make check`.

**2. Reachability by construction, not by reading and agreeing — `tests/runtime/test_turn_cycle.py`.**

Runs the real `runtime.turn.take_turn` (the same function `score-d014-against-a2web` called, minus
the real executor) against a `FakeExecutor`, which already records the `Invocation` object it was
handed (`self.invocations`, existing fixture infrastructure, `test_the_frame_carries_no_plumbing`
uses the same pattern). Asserts on `executor.invocations[0].render()` — the literal string
`take_turn`'s one, unconditional `Invocation(...)` call site produces — that the new directive text
is present. This is not a hand-built `Invocation` asserted in isolation: it is what the production
call site, exercised through the public entry point, actually constructs. If a future edit moves
the vocabulary line, changes its wording back, or the call site starts omitting `vocabulary=` under
some branch, this test fails without anyone reading source.

**Both receipts run in the default (non-`live`) suite, cost $0, and require no `claude` binary.**
Neither substitutes for the thing only a live run can show — whether an agent, under real budget
and real complexity, actually converges on including `effects`/`verified_by` now. That is
explicitly not claimed here: see "What this does not prove" below.

## What this does not prove

Matching `teach-event-vocabulary`'s own honesty about its receipt's limits: this change proves the
directive is present, worded imperatively, positioned near the write action, and cannot silently
drift from the code's actual required fields. It does **not** prove an agent under real budget
pressure will act on it — that is exactly the class of claim the dispatch forbids spending money to
check right now (budget exhausted, run held for Denis's decision). The next live `take_turn` against
a2web is the check; until then this is a wiring receipt, not a behavior receipt, stated as such.

## The trailer decision, stated so the next dispatch can make it rather than rediscover it

Three receipts (`run-a-turn-against-a2web`, `score-d014-against-a2web` ×1 explicitly, and this
change's own read of `D014`'s trail) have now found the same open architecture question: workspace
commits (the agent's commit inside `a2web`, e.g. `9e183e4`) carry no `Yosefactory-Run` trailer,
because `turn.commit()` composes both platform trailers via `git interpret-trailers` only against
`places.queue` — never against the workspace, which the *agent itself* commits, inside its own
sandboxed turn, following `FRAME`'s prose instruction. The decision nobody has made: **who commits
the workspace's own work — the platform, or the agent?**

- **Option A — the platform commits the workspace instead of the agent.** After `may_write_done`
  passes, `turn.py` itself runs `git commit` in the workspace with the trailers composed, instead
  of trusting the agent's own commit. Cost: the platform must now compose a correct commit message
  from the `done` event's `effects` (message quality moves from "whatever the agent wrote,
  presumably following the target repo's convention" to "whatever this repo can derive
  mechanically") and must handle a workspace the agent left uncommitted, partially committed, or
  committed on the wrong branch.
- **Option B — a `prepare-commit-msg` hook installed for the run.** The container mounts a hook
  into the workspace for the duration of the turn that appends the trailer to whatever message the
  agent's own `git commit` supplies. Cost: a hook that must be installed and torn down per-run,
  scoped to a mounted foreign repository the platform does not own, and invisible to anyone
  inspecting the workspace outside a live turn.
- **Cost of neither (status quo, unchanged by this change):** the commit is real but
  un-machine-joinable to its run from the target repo's own history — D014's 2026-08-17 ruling
  already accepted this and moved scoring to the ledger row instead, so nothing is currently broken
  by leaving it open. The decision is overdue as an *auditability* property (a future reader of
  a2web's log cannot tell which commits came from the platform without cross-referencing this
  repo's ledger), not as a blocker to D014 itself.

This change does not pick between A and B — both are architecture-sized, outside a two-line-reword
change's scope, and the dispatch asked for the decision stated, not made.

## Migration

None. Both edits are text-only (a comment string, a skill file); no schema, no config, no signature
change.
