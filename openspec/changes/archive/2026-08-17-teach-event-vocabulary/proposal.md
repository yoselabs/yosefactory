## Why

`add-take-turn-integration-receipt` (archived 2026-08-16) found, on a real run against a real
`claude` binary, that an unattended agent cannot legally reach `done`: it does the work correctly,
then invents an event name (`goal_met`) because nothing reachable by it names the actual vocabulary
(`done` needs `effects` and `verified_by`; ten other events, each with its own required fields — the
full table lives only in `openspec/specs/backlog-item-format/spec.md`). `take_turn` correctly refuses
the invented event. This is D014's kill-criterion blocker: the unit is a commit produced *through the
platform*, and the platform's own `done` gate is currently unreachable by anything that has not read
source it was never pointed at.

## What Changes

- **`Invocation` gains a third plumbing field, `vocabulary: Path | None`** (`executor/invocation.py`),
  rendered as one line: `"The event vocabulary is defined at {path}."` — beside the existing skill
  and proposal-path lines, never inside the frame.
- **`protocol/backlog.py` gains `VOCABULARY_SPEC`**, an absolute path to
  `openspec/specs/backlog-item-format/spec.md`, resolved from `__file__` (this repo is run in place,
  never installed as a wheel — `pyproject.toml`/`CLAUDE.md` confirm single-user, in-repo operation).
  `ITEM.rules` already IS the vocabulary — `VOCABULARY_SPEC` names the one human-readable place an
  agent can read the same table without executing Python.
- **`runtime/turn.py`'s single `Invocation(...)` construction site** passes `vocabulary=backlog.VOCABULARY_SPEC`
  unconditionally. No new `take_turn` parameter: there is exactly one vocabulary, protocol-frozen, not
  a per-workflow choice like `skill` is.
- **`workflows/turn-skill.md` is untouched.** The pointer lives in the surrounding prompt
  (`Invocation.render()`), not inside the skill file the 120-word test measures — see Decision 1.
- **`tests/runtime/test_turn_integration.py` extended**, not rewritten: the existing `FAILED`-path
  assertions stay (a run that predates the fix genuinely failed that way, and that failure mode — an
  unknown event correctly refused — is still exercisable and still worth a receipt). A new test drives
  a real turn with `test_command=("true",)` (the throwaway workspace has no pytest suite) and asserts,
  from the subject: `Outcome.ADVANCED`, the item's log ending in a `done` line with `effects` and
  `verified_by` present, and the workspace commit this `done` event names really exists.

## Decision 1 — where the vocabulary lives: point, don't inline

**Argued, not assumed, per the deferred scope this change closes.**

`workflows/turn-skill.md` carries a 120-word test. That ceiling exists because of this repo's
standing rule — *no workflows in code, only functions*; sequencing is implied by state, invariants
live in the fold — and because prompt-adherence to a large instruction set was already measured
unreliable elsewhere in this program. The full vocabulary table (11 events, most with 2-4 required
fields) is ~150-200 words on its own; inlining it blows the ceiling and the ceiling's own reasoning
does not obviously except it, since a prompt is a prompt regardless of why a given paragraph is long.

But the vocabulary is not *workflow* in the sense that rule was arguing against. It names no
sequencing and no invariant the fold doesn't already enforce independently (`eventlog`'s `Declaration`
rejects an illegal transition or a missing field regardless of what the prompt said) — it is the
**interface**: the literal names and shapes the agent must emit to be understood at all. `frame` uses
exactly this test (D019, `philosophy.md` C2) to decide it belongs in `protocol/`, frozen and small;
the vocabulary table already lives there, twice — once as enforced code (`protocol/backlog.py`'s
`ITEM.rules`) and once as its human-readable mirror (`backlog-item-format/spec.md`).

**Two live options, both real, argued against each other:**

| | Inline in `turn-skill.md` | Point via `Invocation` (chosen) |
|---|---|---|
| Cost | ~150-200 words added to a file with a 120-word test; the test's rationale would need reargued case-by-case, and the file drifts from the spec the moment either is edited alone | one absolute-path line, unconditionally in the prompt every turn |
| Drift | two definitions of one table, one of them prose a human edits by hand | `openspec/specs/backlog-item-format/spec.md` is the sole definition; nothing else states it |
| Precedent | none — this would be the first place the skill body duplicates protocol content | `skill=` already carries an absolute path resolved from a foreign cwd, proven working in the archived receipt |
| Read cost the agent pays | already paid — it is inline, no extra tool call | one more `Read` the agent must actually perform; if it doesn't, the failure mode is identical to today's (an invented event, refused) |

**Chosen: point.** The read-cost row is the honest weakness — a pointer only works if the agent
follows it, and "may not perform the read" is a real risk this proposal accepts rather than dissolves.
It is accepted because the alternative's cost (a second, hand-maintained copy of a frozen protocol
table, inside a file whose whole design premise is that it stays small) is a standing liability, not a
one-time one, and because the receipt this change adds is exactly the test of whether the agent does
follow it — if it doesn't, that is itself the next finding, observed rather than argued away.

## Decision 2 — the frame stays out of it

The event name and its required fields are reporting mechanics: they describe how the agent must
*report*, not what the work *is*. D019's frame (`goal`, `method`, `assumptions`) is the unit compared
run-to-run for falsifiability; a previous worker refused to put a file path in `method` for exactly
this reason, and refused an `instruction` key inside the frame for the same reason one level less
visibly (`add-take-turn-integration-receipt/design.md`). `vocabulary` joins `skill` and
`proposal_path` in `Invocation` — plumbing, disposable, never in the trail — not in `frame`. The spec
delta below makes this an explicit, checked scenario rather than an implicit convention three fields
happen to currently honour.

## Non-goals

- **Not a change to `verify.may_write_done`, any `IsolationPolicy` posture, or any guardrail.** The
  gate that gave the original finding its force is untouched; this change only makes the vocabulary
  reachable, never easier to satisfy dishonestly.
- **Not CI wiring, not a general "teach the agent things" mechanism.** One field, one constant, one
  wiring site.
- **Not a rewrite of `backlog-item-format/spec.md`.** It already states the vocabulary correctly and
  completely; this change only makes it reachable.

## Verification — three checks the coordinator required before apply, each answered from the subject

**1. `__file__`-derived `VOCABULARY_SPEC` is a dev-checkout assumption.** Confirmed, not fixed with a
packaging story it doesn't need yet: `Path(__file__).resolve().parents[3] / "openspec/specs/..."`
resolves to an existing file in this checkout (verified interactively). Named as a limitation in
`protocol/backlog.py`'s own comment: if yosefactory is ever installed apart from its own `openspec/`
tree, the path silently points at a file that does not exist there, and the agent's `Read` fails
rather than teaching it anything. No second deployment model exists today, so nothing was invented to
guard against one.

**2. Read from a foreign cwd, of an absolute path outside the workspace, under `workspace_scoped`.**
Not assumed from `skill=` already working — a separate real probe (`claude.run()` directly, `$0.276`)
confirmed it for `VOCABULARY_SPEC` specifically: `outcome: success`, and the run's own stream shows
`Read {"file_path": "/Users/iorlas/Workspaces/yosefactory/openspec/specs/backlog-item-format/spec.md"}`
with no `permission_denials`. See `tasks.md` §3.3 for the full spend table.

**3. "Read the spec" vs. "guessed right."** `test_a_real_agent_reaches_done_once_the_vocabulary_is_reachable`
asserts on the run's own transcript (`tool_calls(transcript_path, "Read")`) that a `Read` of
`str(backlog.VOCABULARY_SPEC)` actually occurred, not just that `Outcome.ADVANCED` resulted. Confirmed
on the real run this change's receipt drove.

**A fourth thing checked though not asked for:** the two existing `FAILED`-path tests were not deleted,
per the coordinator's note that they still cover a real, reachable failure mode. What that mode *is*
changed — verified, not assumed, by re-running
`test_take_turn_drives_a_real_agent_against_a_real_foreign_workspace` for real ($0.278): the ledger
row's own `note` reads `"VERIFICATION FAILED: tests: pytest -q exited 5: no tests ran in 0.01s"`,
`enforced_by: harness` — the agent now writes a legal `done`, and the independent verification gate,
not the vocabulary, is what refuses it in a throwaway workspace with no test suite.

## Impact

- `src/yosefactory/executor/invocation.py` — new field + render line.
- `src/yosefactory/protocol/backlog.py` — new constant.
- `src/yosefactory/runtime/turn.py` — one call site.
- `tests/runtime/test_turn_integration.py` — extended.
- `openspec/specs/turn-cycle/spec.md` — one requirement gains a scenario (Decision 2).
- **Real spend budget: $1.00.** Report actual spend per run in `tasks.md`; stop and report rather than
  take a third paid attempt at the same wall.
