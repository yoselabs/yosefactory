# Exploration — add-run-guardrails

Dispatched by the P160 visionary session, 2026-08-16. Promotion sources: `D021`,
`architecture.md` §6 (I9) and §7b, `design-e2e.md` §1 and §5b.

Explore only. No code written. This file exists so a stranger — including a
compacted successor to this session — can resume from files alone.

## Ground truth of the repo, checked rather than assumed

| Path | State on 2026-08-16 |
|---|---|
| `src/yosefactory/{protocol,runtime,server,workflows}/__init__.py` | all 0 bytes |
| `tests/` | one smoke test |
| `workflows/*.yaml` | two workflow definitions, data only, no executing code |
| `ledger/*.toml` | 3 rows, hand-authored session summaries |
| `openspec/changes/` | `define-backlog-frame-format` (YF-1), `define-question-frame-format` (YF-2), this |

**There is no executor, no turn loop, and no runner.** Nothing in this repo
currently spawns an agent. That is the single fact that shapes this change.

## The layer split, applied

The structural rule is C2: *would existing ledger rows still be readable and
comparable if this changed next month?*

| Piece | Layer | Reason |
|---|---|---|
| the outcome enum `advanced \| blocked \| nothing-ready \| failed` | `protocol/` | written into every turn record; changing it invalidates comparison across rows |
| turn-record fields the detectors read (`outcome`, `enforced_by`, `isolated`, `dirty`, timestamps) | `protocol/` | same |
| I9 as an invariant — `done` is writable only behind an independent check | `protocol/` | it is the type, not the check |
| the concrete checks (pytest exit, `git log`, `git status --porcelain`) | `runtime/` | replaceable per project without breaking old rows |
| stall-detector threshold N, wall-clock seconds, turn ceiling | config | tuning; rows stay comparable when they move |
| stall-detector and wall-clock *mechanism* | `runtime/` | |
| isolation assembly (`--settings`, `--mcp-config`, clean `$HOME`) | `runtime/` | but see F4 — ownership is contested |

`protocol/` is meant to stay tiny. What this change proposes to freeze there is
an enum, a record shape, and one invariant. Nothing else.

## Findings

### F1 — Two of the five requirements are runnable today; three are not

The dispatch calls this change independent of everything else. Half true, and
the half that is false matters:

```
  runnable NOW, against artifacts that already exist
    stall detector      reads ledger/ (or a turn-record stream) + git log
    I9 verification     reads pytest exit, git log, git status --porcelain

  needs a subprocess that does not exist yet
    wall clock ceiling  there is nothing to time
    turn ceiling        there is nothing to count turns of
    isolation           there is no invocation to isolate
```

The three on the right are not blocked *conceptually* — they are enforcement
wrappers, and a wrapper can be written and unit-tested against a stub process.
But they will have exactly one caller, written later by someone else, and a
guard whose only caller does not exist yet is a guard that has never been proven
to fire. Proposed handling: ship them as a supervisor API with tests that drive
a real short-lived subprocess (`sleep`, a script that exits non-zero, a script
that writes nothing), and state plainly in the proposal that their integration
receipt is owed by whichever change writes the executor.

### F2 — Absence is the mechanism, in three places, and it is one mechanism

Three separate rules in the design record turn out to be the same rule:

- architecture §7b rule 1 — *no terminal structured event means failure, even on exit 0.*
- the stall detector — *no `advanced` in the last N records means alarm, even if all N are green.*
- build-loop.md — *a mechanism that has never fired is a signal; absence is the evidence this corpus loses.*

So the guardrail library's core predicate is not "did something bad happen" but
"is the thing that should be here missing". Concretely, this forbids two
defaults that would otherwise be natural:

- a missing turn record must not be skipped as "no data" — it is `failed`
- `nothing-ready` must never be counted as success anywhere in the codebase

**The predicted failure this change exists to catch is 300 green runs and zero
output.** A detector that treats green as evidence of health cannot catch it.

### F3 — A wall-clock kill cannot write its own turn record

architecture §7b rule 2: a harness-enforced stop is a SIGKILL mid-edit, and a
torn workspace must not read as a clean one. Consequence the dispatch does not
spell out but which falls straight out of it:

```
  agent process   ──SIGKILL──▶   writes nothing
  supervisor      ──────────▶   writes outcome=failed
                                       enforced_by=harness
                                       dirty=<git status --porcelain non-empty>
```

The outcome enum therefore needs **two writers** — the agent for its own verdict,
the supervisor for verdicts the agent cannot deliver — and the record must say
which. Without `enforced_by`, a killed run is indistinguishable from a run that
failed honestly, and `dirty` is what stops a half-edited tree being read as a
clean one on the next turn.

### F4 — Scope collision risk: isolation is executor-invocation code

D021 decides the executor is a thin wrapper per vendor. The isolation controls
(`--settings`, `--mcp-config`, `--allowedTools`, asserting a clean `$HOME`) are
flags passed at invocation — i.e. they live inside the wrapper that this change
does not own and that another worker will likely be dispatched to write.

Proposed split, to be confirmed by the visionary rather than assumed:

- **this change owns**: the isolation *policy* — a typed, defaulted-to-isolated
  config object; the `isolated: bool` field recorded in the turn record (D021
  requires opting out to be explicit and recorded); and a preflight assertion
  that `$HOME` is clean, which is a check, not an invocation.
- **the executor change owns**: turning that policy into actual CLI flags.

The `--bare` trap is confirmed in D021 and needs no re-litigating: `--bare` does
not read `CLAUDE_CODE_OAUTH_TOKEN`, so on a subscription `--bare` and isolation
are mutually exclusive. The policy object must therefore never emit `--bare`.

### F5 — Turn records are not the ledger rows this repo currently has

`design-e2e.md` §1 describes a turn record. `ledger/*.toml` today holds three
hand-authored session summaries whose `outcome` is free text
(`"T17 not settled, leans against..."`), not the enum.

D002 forbids deleting and, read properly, forbids retrofitting: the three
existing rows stay exactly as they are. So the detector must (a) read a stream
where the enum is guaranteed, and (b) never silently coerce a legacy row into
`advanced`. Cleanest reading: turn records are a **new append-only stream**
(`ledger/runs/` or similar), the enum is mandatory there from row 1, and the
three existing rows are out of the detector's scope by construction rather than
by a special case in the code.

### F6 — No spend cap, by decision, and the reason is worth carrying

D021: usage credits are OFF, so on exhaustion requests stop rather than flowing
to metered API rates. No invented spend cap. Build the detector, learn the
condition, decide later.

Note this does **not** remove `--max-turns`: a turn ceiling is a loop-runaway
guard, not a spend cap, and design-e2e §5b records that it has no default limit.
Keeping it is consistent with D021, not a violation of it.

### F7 — Public repo

Nothing in the config surface may carry a token, an OAuth credential, or a
`$HOME` path that identifies the operator's machine. The isolation preflight
asserts on `$HOME` — it must report a boolean, never echo the path.

## What explore did not overturn

The dispatch survives. All five requirements are real, correctly sourced, and
none of them is unbuildable. The corrections above are scope-shape (F1, F4, F5)
and one consequence the dispatch implies but does not state (F3).

## Open, for the visionary — not blocking

1. **F4** — does this change own the isolation policy only, or the invocation too?
   Default assumption if unanswered: policy only, as split above.
2. **F5** — new `ledger/runs/` stream for turn records, or extend the existing
   ledger row shape? Default assumption if unanswered: new stream, legacy rows
   untouched.

## Trail
- 2026-08-16 — explore run by YF-3 on dispatch. Repo state verified directly;
  no design entity was contradicted, so nothing is owed to P160 from explore
  alone.
