## Why

[[D014]] measures one thing: *a commit to a2web produced through the platform*. Nothing in a
commit currently says whether the platform produced it. A hand-driven Claude Code session and a
platform turn emit the same `Co-Authored-By: Claude <model>` trailer, so the criterion's unit
cannot be read off its own artefact — the instrument cannot separate the measured quantity from
its null hypothesis, and a seven-day breach is therefore unprovable in either direction.

Denis authorised the mechanism (`orchestration.md`, 2026-08-16): *"fine to leave what harness
provides. but later on we will add yosefactory as another co-author."* [[H565]] holds that this
program's attribution record is expiring rather than missing, which puts a date on "later on".

**No entity id exists for this promotion.** The director allocates ids; this change cites D014 and
H565 as the entities it serves and claims none of its own.

## What Changes

- Every commit produced by the platform's commit path carries **two** trailers in addition to
  whatever the message already holds:
  - `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` — the authorship claim, in the form
    Denis named and in the one trailer convention every git tool already parses.
  - `Yosefactory-Run: <run_id>` — the route from the commit back to its receipt in the turn-record
    stream.
- Trailers are **appended by deterministic code at the commit call**, never composed by the agent
  and never mentioned in a skill file.
- Existing trailers are preserved, never replaced. A message that already carries a harness
  `Co-Authored-By` keeps it; git's co-author convention is a set, not a slot.
- The run id becomes an argument of the commit path, which today does not receive it.

## Capabilities

### New Capabilities

- `commit-attribution`: what a platform-produced commit carries so that a later reader can tell it
  from a hand-driven one and reach the run record that explains it. Frozen format: every commit
  ever written is compared against every other, so a format change breaks comparability the same
  way a change to the outcome enum would.

### Modified Capabilities

*(none — `turn-cycle` already requires that a turn commits only the paths it wrote; what those
commits carry is a separate, longer-lived question and gets its own spec.)*

## Impact

- `src/yosefactory/runtime/turn.py` — `commit()` gains the run id and appends trailers; its three
  call sites in `take_turn`/`_finish` pass it.
- `tests/runtime/test_turn_cycle.py` — new coverage; existing assertions unchanged.
- No other module. No configuration. No dependency.
- **Not touched:** a2web, `ledger/*.toml`, any existing commit, any git history.

## Non-goals

- **Retrofit.** No existing commit is amended, rebased, or annotated, here or in a2web ([[D002]]).
  The inconsistency is resolved forward.
- **Verifying commits the platform did not make.** A turn could compare `HEAD` before and after the
  executor and refuse commits it did not author. That is a real hole and a different change; it is
  reported to the director rather than absorbed here (Article VI).
- **Recording the platform's own version in the trailer.** Useful for root-causing a breach, and it
  belongs in the run record, which the trailer already reaches. Two copies would drift.
- **A D014 counting tool.** This change makes the count *possible*. Whoever counts is downstream.
- **Changing the harness trailer, or configuring git.** Nothing in `~/.gitconfig`, no commit
  template, no hook.
