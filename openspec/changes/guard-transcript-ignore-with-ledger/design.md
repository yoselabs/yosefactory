## Context

`verify.tree_clean(places.workspace)` runs `git status --porcelain` and fails on any non-empty
line, tracked or not — deliberately, since an agent could otherwise pass `done` having written
nothing tracked. Under `Places.local(repo)`, `places.ledger = repo / "ledger" / "runs"` nests inside
`places.workspace = repo`. `executor/claude.py` writes one raw transcript per run at
`runs_dir / f"{run_id}.stream.jsonl"`, deliberately untracked (`stop-publishing-host-paths`: the raw
stream carries whatever the agent read or wrote, unfiltered, including absolute host paths). Under
`Places.local`, that untracked file sits inside the tree the gate just inspected.

`take_turn` **does** commit into `ledger/runs/`: `{slug}.start` (declared before the agent runs),
and `{slug}.json` / `{slug}.wake.json` elsewhere. Only `*.stream.jsonl` is meant to stay untracked.
So the fix cannot ignore the directory — only the one glob.

## Goals / Non-Goals

**Goals:**
- The gate's tree-cleanliness check never counts the loop's own transcript as dirt, under
  `Places.local` specifically (where the defect lives).
- The `.start`/`.json`/`.wake.json` files stay tracked and committable exactly as before.
- The fix holds for any workspace a turn is pointed at — this platform's own repo and a foreign one
  alike — without assuming the workspace's own `.gitignore` carries (or should carry) the rule.

**Non-Goals:**
- Changing `verify.tree_clean`'s semantics (still: any untracked line fails it).
- A CI-only fix — CI already can't hit this (D026: queue and workspace are separate repos there).
- Moving the ledger or the transcript's write location.

## Decisions

**Decision: guard via `.git/info/exclude`, asserted at `take_turn` startup, not a committed
`.gitignore`.**

Three options were weighed (from the dispatch):

| Option | Verdict |
|---|---|
| (a) loop ensures the ignore rule exists in the ledger's workspace at startup | **chosen** |
| (b) `executor/claude.py` writes transcripts structurally outside any judged tree | rejected |
| (c) assertion at startup refusing to run if transcripts would land unignored | rejected as primary; folded into (a)'s no-op branches |

**Why not (b).** Moving the transcript's write location out of `runs_dir` breaks the
`runs_dir / f"{run_id}.stream.jsonl"` convention every reader of the ledger relies on (the record
and its transcript are siblings by construction), and does not generalize: the *ledger itself* is
platform bookkeeping meant to live under the workspace in the common case (`Places.local` is "every
turn until now"), so "outside the judged tree" is really "outside the ledger," which is a bigger,
riskier move than fixing the one glob that should never have been trackable in the first place.

**Why not (c) as the primary fix.** An assertion that refuses to run is a correct fallback for the
case where the guard genuinely cannot be written (no `.git` — not a worktree at all), but as the
*primary* mechanism it turns every `Places.local` turn against every fresh clone of a foreign
workspace into a hard stop until a human intervenes, for a condition this code can simply make
true itself. (c) survives in the design as the no-op branches: if `workspace` is not a git
worktree, the guard silently does nothing — the pre-existing behavior in that case is `git status`
itself failing loudly inside `verify.tree_clean`, which is assertion enough.

**Why `.git/info/exclude` and not a committed `.gitignore`.** The workspace is whatever repo a turn
is pointed at — this platform's own source tree under `Places.local` in practice today, but by
design (`turn-places` capability) potentially any foreign repo (`a2web`, and whatever comes after
D026 lands elsewhere). Writing a committed `.gitignore` line would mean this platform silently
edits and (implicitly, via the next commit) publishes a change to a repo it does not own, for every
workspace it ever touches — a `D012`-shaped violation one level down (this platform does not absorb
the corpus; by the same logic it should not leave standing artifacts in workspaces it is a guest
in). `.git/info/exclude` is local to the clone, untracked by git itself, and exists exactly to hold
this kind of machine-local exclusion. It has one real cost: it does not travel with a fresh clone of
the workspace, so a *brand-new* clone would need the guard re-asserted once before it is fully
guarded — which is exactly what happens, because `take_turn` calls `ensure_transcripts_ignored`
unconditionally at the top of every turn. The guard is asserted continuously rather than installed
once, so "does it travel with a fresh clone" is not a real gap: the second a turn runs against
that clone, it is guarded before anything else happens.

**Idempotence and placement.** The function checks the existing `.git/info/exclude` contents before
appending, so repeated calls (every turn) are a cheap no-op after the first. Called at the very top
of `take_turn`, before `runs.open_run` — earlier than the first point a transcript could exist,
so there is no ordering window where a transcript could land before the guard is in place.

**Scope of the no-op branches.** `runs_dir.relative_to(workspace)` raises `ValueError` when the
ledger is not nested under the workspace at all — the cross-repository shape, where nothing here is
needed. A missing `workspace/.git` (not a git worktree) is also a no-op, on the reasoning that this
function guards a git property and has nothing to assert about a directory that has no git
identity at all; `verify.tree_clean`'s own `git status` call already fails loudly in that case for
an unrelated reason (no such command can run there).

## Risks / Trade-offs

- **A workspace with a pre-existing, hand-edited `.git/info/exclude`** — the function only checks
  for its own exact pattern line, so a differently-formatted equivalent rule already present (e.g.
  `ledger/runs/*.stream.jsonl` without the leading `/`) would not be recognized as already-covered
  and a second, redundant line would be appended. Harmless (git de-duplicates effectively, and a
  second matching ignore line is not an error) but not detected as redundant.
- **Read this design does not prove**: that a *real* `claude-agent-sdk` executor's transcript,
  written mid-run by a subprocess rather than a test double, is guarded identically — the regression
  test drives `take_turn` with a `FakeExecutor` subclass that writes the transcript file as a side
  effect, matching the real executor's documented behavior (`runs_dir / f"{run_id}.stream.jsonl"`),
  but does not invoke the real `claude` binary. `tests/runtime/test_turn_integration.py` is the
  existing real-executor receipt and was not extended here — doing so would need a live run under
  `Places.local` specifically, which that file does not currently exercise (it always uses a
  cross-repo `queue`/`workspace` split).
