# ADR-0006 — The executor pins model `claude-sonnet-5` and effort `medium`

**Status:** Accepted
**Date:** 2026-08-20
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** Denis issues a new ruling changing the default model or effort, or a turn
class is introduced whose cost/quality profile argues for a different pair — at which point the
constants change and the record here is superseded, not silently edited.

## Context

`executor/claude.py::build_argv` sent neither `--model` nor `--effort` to the `claude` binary.
Every agent run up to `pin-the-executor-and-close-the-push-grant` (archived 2026-08-20) used
whatever the binary defaulted to at invocation time, and no `TurnRecord` or ledger row said which —
so `ledger/spend.jsonl` costs were not comparable across runs, because the thing that determines
cost was never held fixed or recorded.

Checked against the pinned binary before deciding (Article XII), not recalled from memory: both
flags exist at `PINNED_VERSION` (`claude --help` against the built image, `2.1.225`) with exactly
the documented spellings, and a real invocation confirmed the binary's `system|init` event reports
`model` but never reports `effort` anywhere in the stream — an asymmetry in what can be verified,
not a design choice.

## Decision

`PINNED_MODEL = "claude-sonnet-5"`, `PINNED_EFFORT = "medium"` — Denis's ruling, applied directly
as module-level constants beside `PINNED_VERSION`. `build_argv` sends both on every invocation,
unconditionally, with these as defaults, overridable by the caller — never omitted, never left to
the binary's own default. A run has no "unrequested" state for model/effort the way
`cost_ceiling_usd` has a real "no ceiling requested" state.

The record's provenance is asymmetric and stated as such, not smoothed over: `TurnRecord.model` is
read back from the run's own `system|init` event when present (the stronger receipt — the agent
stating what actually ran); `TurnRecord.effort` has no such source and is recorded from what the
invocation sent, because the binary declines to report it at the pinned version.

## Consequences

- Every ledger row from this point on carries a real, comparable `model`/`effort` pair; D014-style
  cost comparisons across runs are now meaningful in a way they were not before.
- `effort`'s value is an echo of the request, not a verified fact — a reader trusting it as
  equivalent to `model`'s provenance would be wrong; this is documented at the field's own
  definition in `protocol/turn.py` and in `openspec/specs/claude-executor/model-and-effort/spec.md`.
- **Not** a CLI surface: no flag was added to `runtime/loop.py`'s argument parser for either value.
  "Configurable" means the executor's own parameters carry real, overridable defaults for a caller
  in code (a test, a future workflow) — not a new operator-facing knob.
- **Known, unrelated drift, not fixed here:** `PINNED_VERSION` (`2.1.225`) trailed the host's
  installed CLI (`2.1.236`, measured the same session) — noted, not touched; a separate decision.

## References

- `src/yosefactory/executor/claude.py` — `PINNED_MODEL`, `PINNED_EFFORT`, `build_argv`.
- `openspec/changes/archive/2026-08-20-pin-the-executor-and-close-the-push-grant/proposal.md`,
  `design.md` (D1, D2).
- `openspec/specs/claude-executor/model-and-effort/spec.md`.
