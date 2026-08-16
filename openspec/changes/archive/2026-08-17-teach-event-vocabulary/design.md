## Context

See `proposal.md` for the finding and the two argued decisions. Relevant current state:

- `Invocation` (`executor/invocation.py`) is a frozen dataclass with `skill: Path | None` and
  `proposal_path: Path | None`, rendered into the same prompt string as the frame
  (`executor/claude.py`'s `render()`), never into the item's trail.
- `turn.py` constructs exactly one `Invocation(...)` (line ~513), for both the claimed-item and the
  planning branch — one wiring site.
- `protocol/backlog.py`'s `ITEM = Declaration(..., rules={...})` already is the enforced vocabulary:
  every event name, its legal `from_states`, its `to`, and its `required` field paths. This is the
  ground truth the fold checks against; `openspec/specs/backlog-item-format/spec.md`'s table is its
  documented mirror, meant to be read by a person or an agent, not executed.
- `verify.may_write_done` runs `test_command` (default `pytest -q`) inside the workspace before a
  `done` proposal is accepted. The archived receipt's foreign workspace fixture is a bare git repo
  with one seed file — no pytest suite — so a receipt exercising the real `done` path must pass a
  `test_command` the fixture can actually satisfy, or it will fail the gate for a reason that has
  nothing to do with the vocabulary fix. `take_turn` already accepts `test_command` as a keyword
  argument; nothing new is needed to supply one.

## Goals / Non-Goals

**Goals:**
- Make the event vocabulary reachable by an unattended agent without inlining it into
  `workflows/turn-skill.md`.
- Keep the frame free of reporting mechanics — checked by a spec scenario, not just by convention.
- Extend `test_turn_integration.py` with the deferred receipt: a real turn reaching `Outcome.ADVANCED`
  via a real `done` event, verified from the subject.

**Non-Goals:** see `proposal.md`.

## Decisions

**Where `VOCABULARY_SPEC` lives: `protocol/backlog.py`, not `runtime/turn.py`.** The constant sits
beside the `Declaration` it mirrors, so a reader who finds one finds the other, and so a future rename
of the spec file is a one-line fix in the module that owns the vocabulary, not a search through the
runtime layer that merely wires it in.

```python
# openspec/specs/backlog-item-format/spec.md carries this table for a reader without a Python
# runtime; ITEM.rules above is what actually enforces it. This path is how an agent finds the
# mirror -- never a second definition, just the pointer.
VOCABULARY_SPEC = Path(__file__).resolve().parents[3] / "openspec" / "specs" / "backlog-item-format" / "spec.md"
```

`parents[3]` from `src/yosefactory/protocol/backlog.py` is the repo root — verified interactively
against this checkout before writing it into a docstring-adjacent comment, not assumed from the
directory count.

**No new `take_turn` parameter.** `skill` varies per workflow (two are deliberately duplicated, H572);
the vocabulary does not — there is one `backlog-item-format` capability and one table. Making it a
parameter would let a caller silently point at a stale or wrong copy; a constant cannot.

**`Invocation.render()` line order:** skill, then vocabulary, then proposal path — "how to behave,
what you may say, where to say it," matching the order a reader would need them in.

**Receipt `test_command`:** `("true",)`. The gate's `tests_pass` check needs a command that exits 0 in
a workspace with no test suite; `true` is the smallest one that says nothing false. This does not
weaken the gate — a production `take_turn` invocation on a repository that actually has a test suite
still gets `DEFAULT_TEST_COMMAND` unless its caller overrides it, exactly as today.

**Existing `FAILED`-path tests are kept, not deleted.** They still document a real, still-reachable
failure mode (an agent that ignores the pointer, or proposes an event that isn't in the table at all)
and remain useful receipts in their own right. The new test is additive.

## Risks / Trade-offs

- **The agent may not read the pointer.** Named in `proposal.md` Decision 1 as the accepted cost. The
  new receipt is the check: if a real run still invents an event with the pointer present, that is a
  finding for a follow-up change (e.g., strengthening the prompt line, or reconsidering inlining after
  all), not something this change papers over.
- **`test_command=("true",)` is receipt-only.** Anyone reading the test in isolation could mistake it
  for the production default; the test's own comment says otherwise, and `DEFAULT_TEST_COMMAND` is
  untouched in `verify.py`.

## Migration

None — additive field with a default of `None` semantics unused (turn.py always sets it), no existing
caller signature changes in a breaking way.
