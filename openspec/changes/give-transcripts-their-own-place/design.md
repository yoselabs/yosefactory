## Context

`Places` (`runtime/turn.py`) names four independently-addressable roles: `queue`, `ledger`,
`workspace`, and two locks (`turn-places` spec). The raw transcript the executor writes
(`<run_id>.stream.jsonl`) has never had a role of its own — it has always landed wherever `runs_dir`
pointed, which is always `places.ledger`. `runs.ensure_transcripts_ignored` exists because of exactly
that coupling: under `Places.local` and `Places.nested`, `ledger` sits inside `workspace`, so an
untracked transcript there would fail the `done` gate's `tree_clean` check — S237's own defect.

K D034 (decided today, 2026-08-29) rules that transcripts are retained *in full, uncapped, in the
runner repository*, and names the gap directly: the exclusion that fixes S237 also means a
transcript nested under a workspace is thrown away rather than committed — it dies with the
workspace's container. Read together with D033 (the queue nests inside the workspace by default),
this is not a bug in `ensure_transcripts_ignored` — that function does exactly what S237 needed. It
is a missing seam: nothing lets a caller say "commit the ledger's own bookkeeping inside the
workspace, but put the raw transcript somewhere else entirely."

## Goals / Non-Goals

**Goals:**
- `Places` gains a `transcripts` role, independently addressable from `ledger`, defaulting to it so
  every existing caller is unaffected (D034's own text: "a cutoff is explicitly deferred" and this
  change should not force any caller to opt in).
- The executor seam (`turn.Executor`, `executor.claude.run`) accepts where to write the raw stream,
  separately from where the turn's own bookkeeping (`.start`/terminal-record files) lives.
- `ensure_transcripts_ignored`'s call site targets the right directory — the one the transcript
  actually lands in — so its no-op behaviour (already correct for "outside the workspace") applies
  to the configuration this change makes reachable.

**Non-Goals:**
- Editing `ensure_transcripts_ignored` itself. Verified rather than assumed: its existing test
  `test_the_guard_is_a_noop_when_the_ledger_lives_outside_the_workspace` already exercises exactly
  the shape this change needs (a `runs_dir` that is not relative to `workspace`) and needed no
  change.
- Deciding a retention cutoff, or wiring the runner (`factory-state`) to actually pass a
  `--transcripts-dir` pointing at itself. Both are D034's own open items, not this change's.
- Moving the `.start`/terminal-record files. They stay exactly where D028/D033 put them.

## Decisions

**A concrete `Path` field with a per-constructor default, not an `Optional` field that resolves
itself.** The first shape tried was `transcripts: Path | None = None` on the dataclass, resolved to
`ledger` in `__post_init__` via `object.__setattr__` (the frozen-dataclass idiom). It reads cleanly
and needs no constructor to remember the default. It fails `ty` (`make check`'s type gate):
`__post_init__`'s narrowing is invisible to the type checker, so every reader of `places.transcripts`
sees `Path | None` and every call site that needs a concrete `Path` (`ensure_transcripts_ignored`,
the `Executor` call) is flagged `invalid-argument-type`. Fixing that by loosening `runs.
ensure_transcripts_ignored`'s and `Executor`'s own signatures to accept `Path | None` would spread the
optionality outward from a value that is, in fact, never `None` by the time anything reads it —
worse than the field it was meant to simplify. The field is `Path`, required at construction; each of
the three places that builds a `Places` (`Places.local`, `Places.nested`, `loop._places_for`)
computes the same default (its own `ledger`) explicitly. Three call sites carry one line of
repetition each; the alternative pushes `Optional` through every reader.

**`Places.nested`'s own `transcripts` parameter stays `Path | None = None`.** This is a classmethod
argument, not the dataclass field — its optionality is the caller-facing "omit for today's
behaviour" contract, resolved to a concrete `Path` (the freshly-computed `ledger`) before it ever
reaches `Places.__init__`. The dataclass field itself is never constructed with `None`.

**`Executor.transcripts_dir` is a required keyword parameter; `executor.claude.run`'s own
`transcripts_dir` is optional, defaulting to `runs_dir`.** The protocol states the contract every
future executor must satisfy: know where to put the raw stream. The one shipped implementation keeps
an optional parameter so every existing direct caller of `claude.run` (none of which know about
`Places` at all — see `tests/executor/test_integration.py`) needs no change; only `turn.take_turn`,
which does hold a `Places`, is required to pass it, and does, always.

**`ensure_transcripts_ignored`'s call site changes; the function does not.** Before this change it
guarded `places.ledger` (the only place a transcript could land). After, the transcript lands at
`places.transcripts`, so that is what the call now names. The function's own no-op path — `runs_dir`
not `relative_to(workspace)` — already exists and already has a test; this change adds one more
scenario to `tests/runtime/test_places_transcripts.py` proving the wiring (not the function) is what
changed.

**Why not fold `transcripts` into `runs_dir` (i.e., let `runs_dir` mean "write the stream here" and
introduce a new, separate parameter for the ledger)?** That would silently change what every existing
caller of `claude.run` and every `Executor` implementation means by `runs_dir` — a renamed contract
under an unchanged name, exactly what Article VII of the fleet constitution warns a quietly-smaller
(or here, quietly-different) version of a change looks like. Adding a new, additively-optional
parameter instead means every pre-existing caller's behaviour is provably unchanged (see the two
"omitted" tests in `tests/executor/test_claude.py` and `tests/runtime/test_places_transcripts.py`).

## Risks / Trade-offs

**[Risk] A caller sets `transcripts` to a path inside `workspace` but not equal to `ledger`.**
`ensure_transcripts_ignored`'s guard still applies (it is called with `places.transcripts`
specifically), so the `done` gate is still protected — this is not a new hazard, just a
configuration nobody currently constructs. → **Mitigation:** none needed; the existing guard already
covers it.

**[Risk] A future `Executor` implementation forgets `transcripts_dir` and writes to `runs_dir`
regardless.** → **Mitigation:** none built beyond the type signature itself; `ty` will flag a
concrete implementation assigned to `Executor` that omits the parameter (as this change's own
`make check` run demonstrated for every existing stand-in). Not otherwise enforced at runtime — the
same trust level every other `Executor` parameter already has.

**What this change does not prove:** it proves the seam exists and is inert by default (every
existing test still passes unmodified in behaviour), and it proves the seam works when exercised
(the new end-to-end test in `tests/runtime/test_places_transcripts.py` writes a transcript outside a
nested workspace and shows the tree stays clean). It does **not** prove a real runner container
actually retains anything — that is `factory-state`'s wiring, explicitly out of scope, and is a
receipt only that repository's own driver can produce.
