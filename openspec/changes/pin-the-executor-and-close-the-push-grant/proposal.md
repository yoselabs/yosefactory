## Why

Two unstated choices, one theme: an unattended run makes no unstated choices.

1. **Which model and effort ran.** `build_argv` sends neither `--model` nor `--effort`. Every agent
   this factory has run used whatever the binary defaulted to at that moment, and no `TurnRecord` or
   ledger row says which — so `ledger/spend.jsonl` costs are not comparable across runs, because the
   thing that determines cost was never held fixed or recorded.
2. **Whether a turn may push.** `Places.publish_workspace`/`publish_queue` default to `True`
   (`decline-publication-per-place`), so `runtime.loop.main`'s unattended entrypoint attempted
   `git push origin main:main` twice against a repo carrying 51 unpushed commits and a history
   rewrite. It failed only because the container holds no push credential — topology saved it, not
   a decision. D022 §2 granted push for a human-watched turn; nothing in it made publication
   mandatory for an unwatched one.

## What Changes

- **`claude.build_argv` sends `--model` and `--effort` on every invocation**, defaulted to
  `claude-sonnet-5` / `medium` (Denis's ruling) and overridable by the caller — never emitted absent,
  never left to the binary's own default.
- **`TurnRecord` gains `model: str` and `effort: str`.** `model` is read back from the run's own
  `system|init` event (`InitFacts.model`) when present — the stronger receipt, because it is the
  agent stating what actually ran rather than the flag we hoped landed. `effort` is not reported in
  any event the stream carries (measured against the pinned 2.1.225 binary), so it is recorded from
  what the invocation sent; this asymmetry is stated in `design.md`, not smoothed over. Both fields
  default to `""` on records written before this change, so old ledger rows stay readable
  ([[D002]]) — an empty string reads as "not recorded," never as "recorded empty."
- **`runtime.loop.main`/`scheduled_main` decline publication by default when `unattended=True`.**
  `Places.local(repo)` is constructed with `publish_workspace=False, publish_queue=False` on that
  path; the interactive path (`unattended=False`, a human at a keyboard) is unchanged and keeps
  publishing. A new `--publish` flag on the CLI re-opens the grant for the unattended path only —
  the interactive path was never gated on it.
- **`openspec/specs/claude-executor/model-and-effort/spec.md`** (new capability, ADDED) — every
  invocation names its model and effort; the pinned defaults; how the record is populated and why
  the two fields have different provenance.
- **`openspec/specs/containerized-loop/unattended-publication-posture/spec.md`** (new capability,
  ADDED) — the unattended entrypoint declines publication by default; the interactive entrypoint is
  unaffected; how the grant reopens.

## Non-Goals

- **Not a CLI surface for model/effort.** Denis's ruling is one pair, applied directly; no flag is
  added to `runtime/loop.py`'s argument parser for either. "Configurable" means the executor's own
  parameters carry real defaults a caller (test, future workflow) can override in code — not a new
  operator-facing knob.
- **Not a change to `IsolationPolicy` or the container's mount topology.** D3 of
  `run-the-loop-inside-the-container` already states push is blocked by topology (no credential in
  the image); this change adds the policy layer *in front of* that topology, so a future image that
  does carry a credential does not silently regain an unattended push nobody decided on.
- **Not durable, ledger-level persistence of `PublishResult`.** `decline-publication-per-place`
  already named this gap and scoped it out; unchanged here. The receipt for this change is the
  `PublishResult` `publish()` actually returns for a live turn, quoted from the run, not a new
  ledger field.
- **Not a fix to `executor/claude.py`'s `PINNED_VERSION` (`2.1.225`) vs. the host's installed CLI
  (`2.1.236`, measured this session).** Unrelated to either half; noted in `design.md` as an
  observed drift, not touched.

## Impact

- `src/yosefactory/executor/claude.py` — `build_argv` gains `model`/`effort` params with pinned
  defaults; `run()` reads `model` back from `InitFacts` when present.
- `src/yosefactory/executor/stream.py` — `InitFacts` gains `model: str = ""`.
- `src/yosefactory/executor/outcome.py` — `RunResult` gains `model: str = ""`, `effort: str = ""`.
- `src/yosefactory/protocol/turn.py` — `TurnRecord` gains `model: str = ""`, `effort: str = ""`,
  threaded through `to_dict`/`from_dict`.
- `src/yosefactory/runtime/turn.py` — `_dispose`/`_finish` thread `result.model`/`result.effort`
  into the record they write.
- `src/yosefactory/runtime/loop.py` — `main()` builds `Places` with publication declined when
  `unattended=True` unless `--publish` is given.
- `openspec/specs/claude-executor/model-and-effort/spec.md`, new.
- `openspec/specs/containerized-loop/unattended-publication-posture/spec.md`, new.
