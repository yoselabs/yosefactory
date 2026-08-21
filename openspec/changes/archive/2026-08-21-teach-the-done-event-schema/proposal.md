## Why

`score-d014-against-a2web`'s turn 2 did real work — a2web's own `make check` passed, `9e183e4`
landed on `fix-reddit-archive-rescue-escalation` — and the turn still ended `failed`: `'done' is
missing required field 'effects'`. `runtime/turn.py` reaches the vocabulary-validating `append()`
only after the gate passes, so this is the last inch of the whole path, and it is where three
consecutive scored attempts now die (D014's trail, 2026-08-21).

**Verified against disk, not assumed from the dispatch:** `teach-event-vocabulary` (archived
2026-08-17) already wired the fix its own name promises. `runtime/turn.py`'s one `Invocation(...)`
call site (line ~530) unconditionally passes `vocabulary=backlog.VOCABULARY_SPEC`, and
`backlog-item-format/spec.md`'s event table already carries the `Carries` column — `done` reads
`effects, verified_by`, matching `ITEM.rules["done"].required` exactly. The pointer that names
*which fields `done` needs* was already reachable when turn 2 ran. It was pointed at from the very
first line of a long, real, multi-hour coding turn and never mentioned again before the agent wrote
its proposal at the end of it — the dispatch's framing ("never told what it must contain") is not
quite right and is corrected here per Article XII, but the underlying finding stands: **a fact
stated once at the start of a long agentic run is not the same as a fact available at the moment
the agent acts on it.** That is the actual gap this change closes.

## What Changes

- **`workflows/turn-skill.md`** (the skill file, read separately from the main prompt, and the
  text that literally describes the write action) gains one clause: check the vocabulary for the
  event's required fields before writing. No field name is added — the file still names zero
  events and zero fields, same as before. 111 words, under the 120-word ceiling (`test_the_skill_
  stays_short`, S098).
- **`executor/invocation.py`'s `Invocation.render()`** rewords the vocabulary line from a passive
  statement of location ("The event vocabulary is defined at {path}.") to an imperative one: the
  path names required fields, and the agent is told to check it for the event it is about to
  write. Same channel, same position, same pointer — reworded, not extended with schema content.
- **`openspec/specs/turn-cycle/spec.md`**: one new scenario on the existing "The frame is not the
  channel for how a run is invoked" requirement (header and prior three scenarios kept verbatim),
  asserting the write instruction carries the check-required-fields directive and that no field
  name is restated anywhere in frame, skill or invocation.
- **Two new tests, $0, no live agent:**
  - `tests/protocol/test_backlog_fold.py` gains a drift guard: for every event in
    `backlog.ITEM.rules`, its required top-level field names are a subset of the `Carries` cell
    parsed live from `backlog.VOCABULARY_SPEC`'s own table. A future change that tightens a rule's
    `required` tuple without updating the table fails this test.
  - `tests/runtime/test_turn_cycle.py` gains a reachability receipt: `take_turn`, run against a
    `FakeExecutor` (no spend), asserts the `Invocation` the real, unconditional call site
    constructs — not a hand-built copy — renders the new directive text.
- **`Dockerfile:84`**: `~/Documents/Knowledge/Projects/160-ai-factory/decisions/D023-*.md` becomes
  a bare corpus reference (`D023 §4`), matching the tilde-shorthand case the host-path guard is
  documented not to catch, in a public repository.

## Decision — reword and reposition, do not restate, do not touch the gate

Argued in `design.md`. Short version: the schema is already taught once, correctly, at exactly one
place (`ITEM.rules`, mirrored at `backlog-item-format/spec.md`). The defect is not a missing fact,
it is a fact placed too far, in the agent's own attention, from the moment it is needed. The fix
moves the *reminder* — never the *content* — closer to the write action, in the two channels that
are actually read near it: the skill file (read when the agent is about to act on it) and the
invocation preamble (reworded for salience). `verify.may_write_done` and `ITEM.rules` are untouched;
`effects` and `verified_by` stay required, exactly as `score-d014-against-a2web`'s own gate refusal
demonstrated they should.

## Also found — other proposal-shaped events share the same channel, and therefore the same fix

`Invocation.render()`'s vocabulary line is not `done`-specific: it points at the whole table,
identically, on every turn, regardless of which event the agent ends up proposing. `blocked`
(`awaiting`'s six fields), `failed` (`reason`, `attempt`, `retryable`), `needs_split` (`children`)
and every other event share the exact same reachability path and therefore the exact same
distance-from-write-action gap. This change is not scoped to `done` by accident of what happened to
be dispatched — the fix in `turn-skill.md` and `Invocation.render()` improves the pointer for every
event at once, because there is only one pointer. No event-specific code exists to special-case.

## Non-Goals

- Not touching `verify.may_write_done`, `ITEM.rules`, or any gate. `effects`/`verified_by` stay
  required and stay enforced by the fold, not by the prompt (per the existing "Invariants are
  checked by the fold, not by the prompt" requirement).
- Not inlining the vocabulary table into `turn-skill.md`. `teach-event-vocabulary/proposal.md`
  Decision 1 already argued this tradeoff; nothing here overturns it.
- Not fixing the missing `Yosefactory-Run` trailer on workspace commits — reported, not patched,
  per the dispatch. See `design.md`'s Trailer decision.
- Not running a live turn. The scored run's budget is exhausted and held for Denis's decision.

## Impact

- `workflows/turn-skill.md` — one clause added, 111 words (was 94, ceiling 120).
- `src/yosefactory/executor/invocation.py` — one line reworded.
- `openspec/specs/turn-cycle/spec.md` — one requirement gains a fourth scenario.
- `tests/protocol/test_backlog_fold.py` — one new drift-guard test.
- `tests/runtime/test_turn_cycle.py` — one new reachability test.
- `Dockerfile` — one comment line, no build behaviour change.
