## Why

No K project 160 promotion id — this is a direct dispatch against a decay diagnosis, not a
build-what-and-why decision (`orchestration.md` Article VI does not apply the other way: the
director dispatched *how the repo records how it was built*, which is squarely this repo's own
business per `CLAUDE.md`'s "a decision about how it got built -> `decisions/` here").

`decisions/` holds two ADRs (2026-08-13, 2026-08-16). Since then: 190 commits, 20 archived
`openspec` changes, the whole runtime — zero ADRs. The obligation to write one lives only in
`decisions/README.md`, a one-line file in a directory nothing in the normal build loop ever opens.
K's own research (R049#C1) already measured the shape of this failure for subdirectory `CLAUDE.md`
files: an instruction loads only if an agent happens to Read a file in that directory first. A
one-line README nobody is ever pointed at is the same failure with the load-bearing sentence
one level further from the point of action. This is the fourth time this decay pattern has been
found in this program (signal S990) — the fix is to move the obligation to a seam that already
fires, not to restate the rule somewhere else.

## What Changes

- **`openspec/config.yaml` gains `operations.archive.guidance`** — the one seam `openspec-archive-
  change` already reads at archive time (`openspec instructions archive --change <name> --json`,
  step 1 of that skill) and folds into its own workflow as advisory-but-considered guidance. This
  is the point of action: archiving a change is exactly the moment "how it was built" is known and
  still fresh, and it is a step every change already takes, unlike a README nothing points at.
- **The obligation, stated with a concrete test for "non-obvious"**: an archived change that made a
  non-obvious build-time choice leaves an ADR. Non-obvious: *would a future worker plausibly change
  this back without knowing why it is this way* — a pin, a refusal, a topology choice, an amend-vs-
  new-commit call. Not non-obvious: a rename, a test added, a docstring fixed.
- **`decisions/README.md`'s ADR template gains a `Revisit trigger:` header line**, alongside
  Status/Date/Supersedes, matching the header block both existing ADRs already use. A falsifiable
  observation, not "if requirements change" — the same bar K's `SCHEMA.md` has stated in prose for
  mechanisms' `revisit_trigger:` field since day one, never once filled in until it became a named,
  greppable line. `tools/audit.py triggers` now sweeps this field for decisions too (director's
  correction to the original dispatch, which had proposed `Overturned if:` — a synonym `audit.py`
  would not recognise, splitting one review discipline into two half-read ones).
- **Six backfilled ADRs** (0003-0008) for build-time choices made 2026-08-16 through 2026-08-22
  that are currently recorded only in code comments/docstrings: the turn loop's mandatory bound
  with no infinite mode; `turn.commit()` as the sole trailer-composing function; the platform
  delivering the workspace commit by amending `HEAD`, never a new commit; the executor pin to
  `claude-sonnet-5`/`medium`; the container's uid-1000 user, forced by `bypassPermissions` refusing
  root; and the host-path pre-commit guard with its `hostpath-allow` marker.

## Capabilities

No spec-level behavior changes — this is tooling guidance and a documentation backfill, not a
change to what the runtime does. `skip_specs: true` in `.openspec.yaml`.

## Impact

- `openspec/config.yaml` — new `operations.archive.guidance` block.
- `decisions/README.md` — template gains `Revisit trigger:`.
- `decisions/0003` through `decisions/0008` — new ADRs, sequential numbering after 0002.
- No runtime code touched (`src/`, `tools/`, `Dockerfile`, `docker-entrypoint.sh` are read-only
  sources for this change, never edited).

## Non-goals

- **Not a second statement of the ADR rule anywhere else.** Article per the dispatch: this decay
  has been found four times; fixing it by adding another prose statement is the failure mode, not
  a fix. One seam, one guidance block.
- **Not a mechanical detector that blocks archiving without an ADR.** "Non-obvious" is a judgment
  call by design (the concrete test narrows it, does not remove it); a hard gate would either
  under-fire (missing the judgment cases) or over-fire (blocking trivial changes), and
  `orchestration.md`'s own "what is not yet mechanical" table already carries several such rows
  honestly as comments rather than false mechanisms.
- **Not re-deriving or re-litigating the six backfilled decisions.** Each ADR records a choice
  already made and already shipped, grounded in the commit and archived-change history, not a new
  argument for why it should have been made.
- **Not touching runtime code.** Documentation-only change, per dispatch.
