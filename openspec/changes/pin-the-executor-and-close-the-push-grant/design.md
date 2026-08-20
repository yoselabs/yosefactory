Motivation: see [proposal.md](proposal.md). Requirements: see
`specs/claude-executor/model-and-effort/spec.md` and
`specs/containerized-loop/unattended-publication-posture/spec.md`.

## Context

Checked against disk before writing anything (Article XII):

- `src/yosefactory/executor/claude.py::build_argv` sends `-p`, `--output-format`, `--verbose`,
  optionally `--max-budget-usd`, and posture flags. No `--model`, no `--effort`.
- `claude --help`, run against the **pinned** binary (the built `yosefactory-factory:latest` image,
  `CLAUDE_VERSION=2.1.225` in `docker-compose.yml`, matching `PINNED_VERSION` in `claude.py`):
  `--model <model>` (alias like `sonnet` or a full name like `claude-sonnet-5`) and
  `--effort <level>` (`low, medium, high, xhigh, max`) both exist and are documented with those
  exact spellings. **Not taken from memory** — the module's own docstring warns this program has
  been bitten by flags that exist in help text and do nothing, so the check that matters is a real
  invocation, done next.
- A real invocation (`claude -p "Reply with exactly: OK" --model claude-sonnet-5 --effort medium
  --output-format stream-json --verbose --strict-mcp-config`, against the same pinned binary,
  `$0.12`) produced a `system|init` event containing `"model":"claude-sonnet-5"` and **no `effort`
  key anywhere in the event**. Checked the full event, not grepped for the one field expected —
  `effort` is absent from `init`, from every `assistant` message, and from the terminal `result`
  event. The binary does not report the effort it ran at, at this pinned version.
- `runtime/loop.py::main()` constructs `places = Places.local(repo)` unconditionally, before
  branching on `unattended`. `Places.local` defaults `publish_workspace=True, publish_queue=True`
  (`decline-publication-per-place`). Nothing in `main()` or `scheduled_main()` ever sets either flag
  — the unattended path inherits the same publish-both default the interactive path has, despite
  branching on `unattended` for both `--spend-ceiling-usd`'s requiredness and the isolation posture
  three lines later. This is the actual defect the dispatch describes; verified by reading the
  function, not by trusting the dispatch's account of it.
- The dispatch warned to expect an `isolated`-shaped wiring gap here too. Checked: `run_loop`'s own
  `isolated` kwarg (the exact thing that was wrong last time — feeding `take_turn`'s turn-record
  field rather than the executor invocation) is now wired correctly, fixed and receipted in
  `run-the-loop-inside-the-container` (commit `cb2d2fa`, "wire run_loop's isolated kwarg to the
  actual policy"). **No live contradiction found on that specific claim.** The actual gap this
  session found is adjacent, not the same one: the publish flags, never wired at all, on either
  path, until this change.

## Goals / Non-Goals

See `proposal.md` — Non-Goals for the full list. In one line: pin model+effort in code and in the
record; make the unattended entrypoint decline publication by default; touch nothing else.

## Decisions

### D1 — `model`/`effort` are always-sent parameters with real defaults, not an optional pair

**Chosen:** `build_argv(prompt, policy, *, cost_ceiling_usd=None, model=PINNED_MODEL,
effort=PINNED_EFFORT)`, where `PINNED_MODEL = "claude-sonnet-5"` and `PINNED_EFFORT = "medium"` are
module-level constants beside `PINNED_VERSION`. Both flags are appended unconditionally — there is
no branch that omits them, unlike `cost_ceiling_usd`, whose absence is a real, distinct state
("no ceiling requested"). Model and effort have no such "unrequested" state: a run without a model
is not a run.

**Over:** an `Optional[str] = None` pair mirroring `cost_ceiling_usd`'s shape — rejected. The
dispatch is explicit that the wrong shape is "an optional field that can be `None`"; the right shape
is a value that always exists and happens to be overridable. Making it `None`-able would reproduce
exactly the defect this change exists to close, one field over.

### D2 — the record gets `model` from the init event; `effort` from what was sent, and the asymmetry is stated, not hidden

**Chosen:** `InitFacts` gains `model: str = ""`, parsed from the `system|init` event's `"model"`
key — the same event `leaks`/`workspace_scope_leaks` already read for the isolation contract, so
this is the same "verify from what the agent reports, not from what we passed" instrument the
executor already trusts (`claude-executor/isolation-invocation`'s own first requirement). `claude.run`
sets `RunResult.model` from `reader.init.model` when the init event was captured, falling back to
the `model` argument only if the stream never produced an init event at all (a run that failed
before startup — the record should still say what was *requested*, not go blank).

`RunResult.effort` is set from the `effort` argument `build_argv` was called with — there is no
stronger source. This is the weaker of the two receipts and it is documented as such here and in
the field's own place in `protocol/turn.py`, per the dispatch's instruction to say which of the two
a design did and why, rather than silently treating an echo as equivalent to a verified value.

**Over:** inferring effort from `usage.output_tokens_details.thinking_tokens` or similar — rejected,
unmeasured and indirect; a token count is not the same claim as "the binary ran at medium effort,"
and building a heuristic to approximate a fact the binary declines to report is worse than stating
the fact is unavailable and recording the request instead.

### D3 — `model`/`effort` land on `TurnRecord`, not only on `RunResult`

**Chosen:** `TurnRecord` gains `model: str = ""`, `effort: str = ""`, threaded through `to_dict`/
`from_dict` the same way `note` already is — optional, defaulting to `""` on read, so a pre-existing
ledger row with neither key still loads (`from_dict`'s own "a missing key is null rather than an
error" comment already states the policy this follows). `_dispose`/`_finish` in `runtime/turn.py`
carry `result.model`/`result.effort` from the `RunResult` the executor returned into the
`TurnRecord` they write.

**Why the ledger row, not just the executor's own return value:** the dispatch's complaint is that
"nothing in any `TurnRecord` or ledger row" says what produced a cost. `RunResult` is discarded at
the end of `_dispose`; the ledger is what survives. A field that stops at `RunResult` would fix the
argv and lose the record in the same breath.

**Not required, unlike `run_id`/`outcome`/etc.** `_REQUIRED` in `protocol/turn.py` is unchanged.
Making the new fields required would break every pre-existing ledger row's `from_dict` — the same
mistake C2's rigid/soft test exists to catch (`protocol/` "frozen and small," not "frozen and
retroactive"). New writes always populate both (D1 guarantees `build_argv` never omits them, so
every `RunResult`/`TurnRecord` this codebase writes from here on carries a real value) — "never
absent" is a property of the write path, not of the schema's own required-field list.

### D4 — publication declines by default only on the branch that was actually unwatched

**Chosen:** in `runtime/loop.py::main()`, after `places = Places.local(repo)`:

```python
if unattended:
    places = replace(places, publish_workspace=args.publish, publish_queue=args.publish)
```

with a new `--publish` (`action="store_true"`, default `False`) argument. The interactive branch
(`unattended=False`) is untouched — `places` keeps `publish_workspace=True, publish_queue=True`
from `Places.local`, exactly as before this change, because a human running `main()` directly is
the D022 §2 case this grant was written for.

**Over (three, each considered and rejected):**
- **Flip `Places.local`'s own defaults to `False`.** Rejected — `decline-publication-per-place`'s
  own Decision 2 already argued this exact point for the general case and it still holds: three
  existing tests assert every unqualified `Places.local`/bare `Places(...)` construction publishes
  both, and the interactive path must keep doing so. Changing the shared default would silently
  stop publishing for the human-watched case too.
- **A tri-state flag (`--publish`/`--no-publish` as separate switches).** Rejected — `unattended`
  is already the only signal that matters here (same one `--spend-ceiling-usd`'s requiredness and
  the isolation posture both key off, three lines apart in the same function); a second explicit
  "no" state has no caller that would ever choose it over the default, and D022's own reasoning
  (`main`'s docstring: "that premise holds for a person typing this command and does not hold for a
  scheduler") already draws the line at `unattended`, not at a third state.
- **Gate on container mount topology instead of a flag.** Rejected — this is precisely the trap D3
  of `run-the-loop-inside-the-container` already named: topology (no credential in the image) and
  policy (a flag that could be wrong) are different guarantees, and conflating them is how a policy-
  only protection gets reported with a topology-only confidence. This change is explicitly adding
  the policy layer *in front of* the topology one, not relying on the latter to keep doing the
  former's job.

**What reopens it:** `--publish` on the unattended entrypoint's own command line — i.e. a future
Denis editing `docker-compose.yml`'s `command:` list (or the `launchd`/`cron` invocation) to add
`--publish` alongside `--max-iterations`/`--spend-ceiling-usd`. Nothing else — not an env var, not a
config file — reopens it, so the grant is visible in the one place an operator already reads before
changing how the loop is invoked.

## Risks / Trade-offs

- **`effort`'s provenance is weaker than `model`'s, and a reader of the ledger who does not read
  this file could mistake one for the other.** Mitigated by D2's own field-level documentation in
  `protocol/turn.py` and by `model-and-effort/spec.md` stating the asymmetry as a requirement, not
  an implementation detail — a reader checking the spec, not just the code, still finds it.
- **A future binary version might start reporting `effort` in `init`.** Not handled specially —
  `claude.run`'s fallback (echo the argument) only fires when the init event carries no `model`
  either; extending the same "prefer init, fall back to what was sent" shape to `effort` the day the
  binary reports it is a one-line change, not a redesign.
- **`--publish` is a new flag nobody has used yet.** Receipted below by a live run showing the
  *declined* path; the reopened path is argued (D4) but not separately live-run in this change — a
  container invocation with a push credential present does not exist yet to demonstrate it against,
  and manufacturing one only to prove a flag flip would cost a real credential grant this change is
  not asking for.

## Migration

None. Both halves add fields/parameters with defaults that reproduce prior behaviour for every
existing caller except the one path this change deliberately changes (`scheduled_main`'s publish
default). No existing signature loses a parameter or changes required-ness in a breaking way.
