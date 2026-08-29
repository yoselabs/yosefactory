# ADR-0019 — `Places.transcripts` is a plain `Path`, defaulted per constructor, not an `Optional`
that resolves itself

**Status:** Accepted
**Date:** 2026-08-29
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a fourth `Places` constructor is added (beyond `local`, `nested`,
`loop._places_for`) that would need to duplicate the same "default to my own `ledger`" line a
fourth time. At that point re-open whether a shared helper (e.g. a module-level
`_default_transcripts(ledger)`, or reintroducing the rejected `__post_init__` shape behind a typed
accessor) is worth the indirection.

## Context

K D034 ("central control plane, local state, and the event is the wake not the assignment") rules
that raw executor transcripts are retained in full in the runner repository, and names the defect
this change (`give-transcripts-their-own-place`) exists to fix: `runs.ensure_transcripts_ignored`
correctly keeps `*.stream.jsonl` from dirtying the workspace tree the `done` gate inspects, but
under `Places.nested` (K D033) the ledger it guards sits *inside* the workspace, so the same
exclusion means the transcript is never committed and is lost when the workspace's container exits.

`Places` needed a fifth, independently-addressable role — where the raw transcript lands — separate
from `ledger` (where the `.start`/terminal-record files live, which continue to ride the ledger's
own commit). Every existing caller needed this to be inert: omitting an opinion about transcripts
must reproduce today's behaviour exactly.

## Decision

`transcripts: Path` is a required field on the `Places` dataclass, with no class-level default.
Each of the three places that constructs a `Places` (`Places.local`, `Places.nested`, `runtime.loop.
_places_for`) computes the same default explicitly — its own `ledger` — and passes it. A caller that
wants transcripts somewhere else passes a different value (`Places.nested`'s own `transcripts`
keyword argument, or `loop._places_for`'s `transcripts` parameter, both `Path | None = None` and
resolved to a concrete value before `Places.__init__` is ever called).

## Why this over the alternative tried first

The first shape was `transcripts: Path | None = None` on the dataclass itself, resolved to `ledger`
in `__post_init__` via the standard frozen-dataclass idiom (`object.__setattr__`). It reads cleanly:
one field, one place that knows the default, no repetition across constructors.

It fails `ty` (`make check`'s type gate), and not narrowly: `__post_init__`'s narrowing is invisible
to the type checker, so every reader of `places.transcripts` sees `Path | None` regardless of the
runtime guarantee that it is never `None` by the time anything reads it. Three call sites were
flagged `invalid-argument-type` — `ensure_transcripts_ignored`, and both `Executor.__call__` sites in
`turn.take_turn`. The available fixes were: (a) loosen every downstream signature that consumes
`places.transcripts` to accept `Path | None`, pushing the optionality outward from a value that is
never actually optional at the point of use, or (b) assert-and-narrow at every read site, which is
the same repetition as (c) below but with a runtime assertion added for no benefit, or (c) make the
field concrete and resolve the default once per constructor. (c) was chosen: three constructors each
carry one extra line (`transcripts=<their own ledger>`), which is less code than either (a) or (b)
and leaves no `Optional` anywhere a `Path` is actually guaranteed.

## What this does not decide

- Whether `factory-state` (the runner repository, private, Denis's own) actually passes
  `--transcripts-dir` pointing at itself. That is wiring on a repository this change does not touch,
  named by D034 as the destination and left to its own driver.
- A retention cutoff for accumulated transcripts. D034's own body defers this explicitly.
