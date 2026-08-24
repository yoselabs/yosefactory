# ADR-0018 — Event payload shapes are validated by extending `Rule`, not by a second schema

**Status:** Accepted
**Date:** 2026-08-24
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a payload shape is found that this mechanism cannot express without
duplicating what `Rule.required`/`.patterns` already declare — e.g. a field whose legal shape
depends on another field's value, or nested per-branch sub-field requirements on a union-typed
field like `resolution`. At that point re-open the pydantic/`TypedDict` alternatives this ADR
rejects, since the "one declaration" argument for extending `Rule` would no longer hold.

## Context

[[D032]] (K project 160): an event payload SHALL be a validated structure, not a bare dict,
following [[S246]] — `backlog.context()`'s `unblocked` branch called `.get("answer")` on
`resolution` assuming it was always a mapping; `backlog-item-format/spec.md` already required a
string (`"timeout"`) for the deadline-sweep case. Neither `ty`, `ruff`, nor 400+ tests caught it.
D032 records the ruling ("strict structures, maybe pydantic, strict typing") and explicitly defers
the mechanism to this repo.

`protocol/eventlog.py`'s `Rule` already declares `required` (presence) and `patterns` (regex on
string values), consulted once per record inside `_fold`'s `_check_payload`. D032 calls this
"already half a schema."

## Decision

`Rule` grows a third field, `types: Mapping[Path_, type | tuple[type, ...]]`, checked in
`_check_payload` next to `required`/`patterns` — same function, same per-record loop, one more
declared property of a path already named there. `ITEM.rules` in `protocol/backlog.py` declares
types for the three events `backlog.context()` reads: `gate_rejected.report`/`.attempt`,
`failed.reason`/`.attempt`/`.retryable`, `unblocked.resolution` (declared as `(str, Mapping)` — the
spec legitimately allows both shapes for this one field).

This runs inside `_fold`, which every `load()` call executes — including against a hand-seeded or
historically-written `.jsonl` file, not only a payload a current writer could produce. That answers
D032's deciding question ("must a malformed event already on disk be caught?") **yes**, which is
why a static-only option (`TypedDict` + `ty`) was rejected outright: it reads the code, never the
disk.

**Rejected: pydantic models per event.** Would sit *beside* `Rule.required`/`.patterns`/
`from_states`/`to`, not replace them — `_fold` already consults `Rule` for legality and absorption
(`_select`'s "first matching rule wins", which has no direct pydantic equivalent). A pydantic layer
would therefore either duplicate what `Rule` already declares (two declarations of the same event,
the exact net loss D032 names as the constraint that matters most) or require replacing `Rule`
outright — a far larger diff touching every event and every existing `required=`/`patterns=` call
site for expressive power ([discriminated unions,](https://docs.pydantic.dev) coercion, richer
error aggregation) this change does not need to close the one gap [[S246]] found.

**Scope, deliberately narrow.** Only the three events `context()` reads carry `types=` entries.
Every other event's payload is untyped after this change — not because their fields are known
safe, but because none is known to carry `resolution`'s specific risk (a reader chain-accessing a
field that assumes one shape). Should the same class of defect surface elsewhere, this ADR's
mechanism extends by one more `types=` line; it does not need re-deciding.

## Consequences

- `openspec/specs/backlog-item-format/spec.md` gains one scenario (via
  `type-the-payloads-context-reads`'s spec delta): a declared type mismatch fails the read, naming
  the field, the value, and the expected type — same posture as the existing malformed-`on_timeout`
  scenario, extended from pattern-mismatch to type-mismatch.
- `pyproject.toml` gains no new dependency. `pydantic` stays a transitive dependency (via
  `fastmcp`), not one this repo's protocol layer takes on directly.
- **Not proven by this change:** that every latent shape-mismatch defect is now caught (only the
  three named events' top-level fields are typed); that `types` composes correctly with a
  multi-`Rule` event (none of the three typed events declare more than one `Rule`); or anything
  about runtime behavior downstream of the fold — this only changes what `load()` admits.
- `isinstance(True, int)` is `True` in Python but `isinstance(1, bool)` is `False`, so a
  `bool`-typed field correctly rejects an int substitute. Noted because it is the one place Python's
  type system is looser than it looks, not because it caused a problem here.

## References

- `src/yosefactory/protocol/eventlog.py` — `Rule.types`, `_check_payload`.
- `src/yosefactory/protocol/backlog.py` — `ITEM.rules["gate_rejected"|"failed"|"unblocked"]`,
  `context()`'s `isinstance(resolution, Mapping)` guard.
- `tests/protocol/test_eventlog_rules.py`, `tests/protocol/test_backlog_fold.py`.
- `openspec/changes/type-the-payloads-context-reads/` (proposal.md, design.md).
- K decision D032, signal S246, project 160.
