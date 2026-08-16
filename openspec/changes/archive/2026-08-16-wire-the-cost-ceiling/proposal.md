## Why

`executor/claude.py`'s own capability table names `--max-budget-usd` as **native** at the pinned
version — measured by running it, not read from help text — and `build_argv` never sends it. A
capability claimed in a declaration and never reached by the argv it is supposed to produce is the
same shape as a typed field with no writer: **it reads as satisfied to anyone auditing the
declaration rather than the invocation.**

Verified against the real binary before writing this proposal: `claude -p --help` lists
`--max-budget-usd <amount>`. No flag for a turn count exists anywhere in its help output — `NATIVE`'s
sibling capability, `turn_ceiling`, stays correctly declared `EMULATED` by the harness, and this
change does not touch it.

**No promotion id.** Surfaced by this worker in exploring `write-the-reason-fields`, dispatched by the
director from that finding.

## What Changes

- `Guardrails` gains an optional `cost_ceiling_usd: float | None`, defaulting to `None` — additive,
  so existing config and every existing call site is unaffected.
- `build_argv` sends `--max-budget-usd <amount>` when a ceiling is set, in both the isolated and
  opted-out invocation shapes.
- **The flag is documented as what it measurably is: a detector, not a ceiling.** YF-4's receipt
  against the pinned binary: cap `$0.02`, spend `$0.048` — 2.4×. The binary checks after a turn
  completes and stops the *next* one; it does not bound the turn that crosses the line. This goes into
  the spec as a normative statement, not a comment a later reader can miss.
- **Not built:** the integration layer that would drive `runtime.turn.take_turn` against a real
  executor. Named as a gap in the previous change's outcome and still a gap after this one — this
  change wires an argument, it does not add the test infrastructure that would exercise it end to end
  through the reducer. If honesty about this flag turns out to require that layer, that is a reason to
  stop and say so, not to build it here.

## Capabilities

### New Capabilities

- `claude-executor/cost-ceiling`: the caller may request a dollar ceiling on a run, the executor
  requests it from the binary when set, and the ceiling is a post-turn detector rather than a
  preventive bound.

### Modified Capabilities

None. `run-interface`'s classification of `BUDGET_EXHAUSTED` already exists and is unaffected — this
change is about the request side, not the response side.

## Impact

- `src/yosefactory/runtime/config.py` — the new field.
- `src/yosefactory/executor/claude.py` — `build_argv`, `run`, and the `NATIVE` table's entry, which
  currently over-claims: it says the capability exists, not that anything sends it. Since this is a
  comment-only string rather than SHALL-governed prose, correcting it is not a spec change.
- `tests/executor/test_claude.py` (or nearest fit) — `build_argv` emits the flag when set, omits it
  when not.

## Non-goals

- **Turn-count / `--max-turns`.** Verified absent from `claude -p --help` at the pinned version.
  Nothing to wire; `EMULATED` already declares it correctly.
- **Preventing overshoot.** The binary's own behaviour is post-turn; this change requests the flag it
  has, not a stronger guarantee it does not.
- **The `take_turn`-against-real-executor integration layer.** Named as a gap by the previous change;
  building it is materially larger than wiring one flag and is not this dispatch.
- **A default ceiling.** `None` stays the default; nothing in this change picks a number for the
  operator.
