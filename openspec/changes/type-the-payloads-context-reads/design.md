## Context

Verified against disk before writing anything below (Article XII):

- `src/yosefactory/protocol/backlog.py:135` on `main` (`ac9a4c3`): `context()`'s `unblocked`
  branch is `answer = record.get("resolution", {}).get("answer")`. Confirmed live:
  `{"resolution": "timeout"}.get("resolution", {}).get("answer")` raises
  `AttributeError: 'str' object has no attribute 'get'`.
- `openspec/specs/backlog-item-format/spec.md:254`, on `main`, already requires: *"the resolution
  is recorded as an `unblocked` event with `resolution: timeout`"* — a string, not a mapping.
  `apply_answers()` (`runtime/turn.py`) is the only current writer of `unblocked` and always
  produces a mapping, so the crash is latent, waiting on the deadline sweeper the spec describes
  and nobody has built ([[S246]]).
- `sweep-blocked-and-snoozed-deadlines` (local branch, unsanctioned per [[S245]]), commit `2262f7e`,
  fixes exactly this in `context()` with `isinstance(resolution, Mapping)` and a comment naming both
  shapes. Denis authorised taking this one hunk. `scheduled_for()`, `sweep_deadlines()`, and
  `runtime/turn.py` from that branch are unreviewed and explicitly out of scope here.
- `protocol/eventlog.py`'s `Rule` (frozen dataclass): `from_states`, `to`, `required: tuple[Path_, ...]`,
  `patterns: Mapping[Path_, str]`. `_check_payload()` walks `required` (presence via `_dig`) and
  `patterns` (regex on string values, skipped when absent) in one function, called once per record
  inside `_fold`. This runs on every record read from a log — including a hand-seeded or
  historically-written one — not only ones a current writer could produce.
- `pyproject.toml`'s `dependencies` lists `claude-agent-sdk` and `fastmcp`, not `pydantic`.
  `pydantic==2.13.4` is present in `.venv` transitively (pulled by `fastmcp`/`pydantic-settings`),
  confirmed by `find .venv -name pydantic -maxdepth 4`. Using it directly would need declaring it
  as a top-level dependency, not just relying on the transitive pin.

## Goals / Non-Goals

**Goals:**
- Fix the confirmed defect: `context()` over an `unblocked` event whose `resolution` is the literal
  string `"timeout"` folds cleanly instead of raising.
- Give `Rule` a way to declare a payload field's *type*, not only its presence, so the next writer/
  reader mismatch on `resolution`-shaped ambiguity fails at read time rather than at whichever
  reader happens to `.get()` it next.
- Apply it to the payloads `context()` actually reads (`unblocked.resolution`, `gate_rejected.report`/
  `.attempt`, `failed.reason`/`.attempt`/`.retryable`) and say what remains untyped and why.
- Keep the prose spec and the runtime declaration as the *same* fact, not two.

**Non-Goals:**
- Typing every event's every field in one change (see Scope below).
- Nested-shape validation of `resolution`'s dict branch (`qid`/`by`/`answer` individually) — the
  defect closed here is the top-level shape ambiguity, not those fields' own types, which
  `required` already partially covers and no reader has yet mis-shaped.
- Migrating `Rule`/`_check_payload` to pydantic. Considered and rejected below.

## Decisions

### The mechanism: extend `Rule`, not a parallel schema

D032 lists three candidates and leaves the choice here. Restated with the deciding question
D032 poses — **must a malformed event already on disk be caught?** — answered **yes**, because
`backlog/` logs are append-only and hand-seeded items exist (`backlog/README.md`'s own worked
fixture is hand-written), so a shape can arrive that no writer in this codebase produced. That
rules out `TypedDict` + `ty` alone: it reads the code, not the disk, and a `.jsonl` file long
predates whatever `ty` sees today.

Between the two runtime-checked options — pydantic models per event, or extending `Rule` — the
deciding factor is D032's **"one declaration, not two."** A pydantic model would sit *beside*
`Rule.required`/`.patterns`, not replace them: `Rule` is what `_fold` already consults for
legality (`from_states`, `to`) and presence, so a pydantic layer would need to either duplicate
that (two declarations of the same event) or replace `Rule` outright (a much larger diff touching
every event, every existing `required=`/`patterns=` call site, and `_select`'s absorption logic,
which pydantic's validators do not natively express — "first matching rule wins" has no pydantic
equivalent short of hand-rolling it again inside a model).

Extending `Rule` with a `types: Mapping[Path_, type | tuple[type, ...]] = field(default_factory=dict)`
field, checked in `_check_payload` next to `required`/`patterns`, adds **one property to an
already-load-bearing declaration** — the same one `_select`, `required`, and `patterns` already
read. It is the smallest diff of the three, and it is smallest *because* it is not a new
declaration: `ITEM.rules["unblocked"]` gains a `types={("resolution",): (str, Mapping)}` entry the
same way it already carries `required=(("resolution",),)`.

**What this does not give up.** Pydantic would express more (discriminated unions with distinct
required sub-fields per branch, coercion, error aggregation). None of that is needed to close
[[S246]]'s specific gap — a bare `isinstance` check on the one field that crashed — and D032's own
constraint ranks "one declaration" above "richer expression." If a future shape genuinely needs
sub-field validation per branch, that is the next change's finding, not something to build
speculatively now (same posture `teach-the-done-event-schema`'s design.md took on mid-run prompt
injection).

### Where the check runs

`_check_payload(rule, record, name, source, line)` already loops `rule.required` then
`rule.patterns`. A third loop, `rule.types`, is added there:

```python
for path, expected in rule.types.items():
    found, value = _dig(record, path)
    if not found:
        continue
    if not isinstance(value, expected):
        raise LogError(f"{'.'.join(path)} is {value!r} ({type(value).__name__}), expected {expected!r}", ...)
```

Types apply **only when the field is present** — same posture as `patterns`, and deliberate:
`required` already owns "must be present"; `types` owns "if present, must be this shape." A field
absent when `required` demands it is already an error from the existing loop; `types` does not
duplicate that check.

`isinstance(True, int)` is `True` in Python, so a `bool`-typed field would silently accept an `int`
`1`/`0` in place of `True`/`False` were one declared. None of the three fields typed in this change
have that ambiguity in practice (`retryable` is the only `bool`, and no writer in this codebase
emits an int there), so it is noted rather than worked around — a future field would need to state
it as a caveat, not a blocker.

### Scope: three events, named because `context()` reads them

`backlog.context()` is the reader [[S246]] found broken, and it reads exactly four sources:
`gate_rejected`, `unblocked.resolution`, `failed`, `released`/`reclaimed`. Typing:

- `gate_rejected`: `report: str`, `attempt: int`.
- `failed`: `reason: str`, `attempt: int`, `retryable: bool`.
- `unblocked`: `resolution: (str, Mapping)`.

`released`/`reclaimed`'s `reason` is **not typed here**, deliberately: `context()` reads it as
`record["reason"]` and stores it verbatim without calling any method on it that would crash on an
unexpected type (unlike `resolution.get(...)`), so it carries none of this defect's risk profile.
Adding it would be scope creep against the stated boundary rather than closing a live gap.

**What remains untyped, and why:** every other event (`created`, `priority_set`, `frame_amended`,
`claimed`, `started`, `released`, `reclaimed`, `blocked`, `snoozed`, `woke`, `falsified`,
`needs_split`, `done`, `cancelled`, `duplicate`, `poisoned`, `abandoned`, `note`) carries no `types`
entry after this change. None of their fields are read the way `resolution.get("answer")` was —
directly chained-accessed by a reader that assumes one shape — so none are known to carry the same
class of latent defect. Should one be found (the same way [[S246]] was), it is D032's revisit
trigger firing again, and the fix is one more `types=` line, not a redesign.

### Spec: one new scenario, not a new requirement

The vocabulary table already lists `resolution`'s two shapes in prose (added by
`carry-inherited-context-into-the-turn`'s MODIFIED block, already on `main`). This change's delta
adds one scenario under "The event vocabulary and its transitions," mirroring the existing
"A malformed on_timeout still fails wherever it appears" scenario's shape: a declared type
mismatch fails the read, naming the field. No new Requirement — this is the same requirement
("legal only from the listed states... payload fields") gaining one more checked property, which
is exactly what "extend `Rule`" is supposed to mean at the spec level too.

## Receipts

**Part 1 (defect).** `tests/protocol/test_backlog_fold.py`: `backlog.context()` over `fold(CREATED,
CLAIMED, STARTED, BLOCKED, unblocked_with_literal_timeout_string)` — where `unblocked.resolution`
is the bare string `"timeout"` — returns `{}` (no crash, no answer folded) rather than raising
`AttributeError`. Fails on `main` before this change; passes after.

**Part 2 (mechanism).** `tests/protocol/test_eventlog_rules.py`: a `Rule` declaring
`types={("field",): int}` rejects a record where `field` is a string, with a `LogError` naming the
field, the value, and the expected type. `tests/protocol/test_backlog_fold.py`: a hand-built
`failed` record with `retryable` as the string `"true"` (a plausible hand-seeding mistake) fails
`backlog.load()` rather than silently folding into `context()["prior_failure"]["retryable"] ==
"true"` (a value that would previously have passed through unnoticed and read as truthy but wrong
by any consumer expecting a Python `bool`).

## What this change does not prove

- That every latent shape-mismatch defect in this codebase is now caught — only the three named
  events, and only their top-level fields. A mismatch inside `resolution`'s dict branch, or in any
  untyped event, is not covered and D032's revisit trigger is the mechanism for finding the next
  one, not this change.
- That `types` composes correctly with `Rule`'s absorption (`_select`, several rules per event) —
  none of the three typed events in this change declare more than one `Rule`, so that interaction
  is untested here.
- Runtime behavior beyond the fold: nothing here changes what `runtime/turn.py` or any executor
  does with a payload once it passes the fold; it only changes whether a wrong-shaped one is
  admitted at all.
