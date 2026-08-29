## Context

`Places` (`runtime/turn.py`) already names four independently-addressable roles: `queue`, `ledger`,
`workspace`, and two locks. `Places.local(repo)` collapses all four onto one repository.
`runtime.loop._places_for` additionally supports `--queue`/`--workspace` as two *separate*
repositories (built for D026: private queue in `factory-state`, public workspace in `a2web`). D033
supersedes that: a workspace's items live inside the workspace's own repository, at
`<workspace>/.factory/…`, not in a repository the runner owns.

Verified before writing any code (scratch test, a real `git init` + subdirectory commit): `git add`/
`git commit`/`git push`, run with `cwd` set to a subdirectory of a repository, resolve pathspecs
relative to `cwd` and operate on the *enclosing* repository correctly — nesting the queue inside the
workspace needs no change to `commit()`, `push_repo()`, or the pathspec logic in `_finish`. The one
place nesting breaks something today: `LOCK = Path(".git") / "yosefactory-turn.lock"` is computed
under whichever path a caller hands in as `queue` or `workspace`, and `.factory` (the nested queue) has
no `.git` of its own — `resolved_queue / LOCK` under the existing `_places_for` logic would create a
bogus `.factory/.git/` directory and lock a file that has no relationship to the actual repository.

## Goals / Non-Goals

**Goals:**
- A queue nested inside its workspace's own repository is a first-class, constructible `Places`
  shape, alongside `Places.local` and the fully-separate two-repository shape.
- The nested queue's lock and the workspace's lock are provably the same file — the two locks stay
  meaningful (each still names what it serializes) without pointing at two different files for what
  is actually one tree.

**Non-Goals:**
- Migrating `factory-state`'s six existing items into any workspace's `.factory/`. Not decided by
  D033 either ("Migration... not decided here").
- Editing `factory-state`'s own workflow or driver. That repository is the director's.
- Changing `publish()`'s two-call shape, or adding a third publish target. D033 keeps the credential
  as the only central component; the queue's push and the workspace's push, under nesting, resolve to
  the same repository and branch, so calling `push_repo` twice is a harmless duplicate (the second
  call reports "Everything up-to-date"), not a new code path. Optimizing that into a single call is
  deferred — see Risks/Trade-offs.
- Deciding whether workspace turns actually run concurrently. D033 states this only makes
  parallelism *possible*; `take-a-turn.yml`'s single concurrency group is untouched here.

## Decisions

**`Places.nested(workspace, queue_subdir=".factory")` — a new classmethod, not a generic
auto-detector.** `Places.local` is a named shape for one specific topology; the nested nesting
deserves the same treatment rather than asking every caller to hand-assemble the four fields (and
risk the lock bug this design starts from). Signature:

```python
@classmethod
def nested(cls, workspace: Path, *, queue_subdir: str = ".factory") -> Places:
    queue = workspace / queue_subdir
    return cls(
        queue=queue,
        ledger=queue / RUNS,
        queue_lock=workspace / LOCK,
        workspace=workspace,
        workspace_lock=workspace / LOCK,
    )
```

`queue_lock == workspace_lock` here (same `Path` value), which is exactly the condition
`_workspace_lock` already tests to decide whether re-acquiring the workspace lock is a no-op — the
same mechanism `Places.local` relies on, reused rather than duplicated.

**`_places_for` (the `--queue`/`--workspace` CLI path) gains one branch: detect nesting.** A caller
may still pass `--workspace <a2web> --queue <a2web>/.factory` by hand (matching how
`scripts/run_a2web_turn.py`-style direct callers already construct `Places` today, pre-D033, with a
central queue). Rather than leave that path silently wrong, `_places_for` checks whether the resolved
queue is inside the resolved workspace and, if so, keys both locks off the workspace — the same rule
`Places.nested` encodes, reachable from the CLI as well as from a direct caller.

**No change to `spend_log_for`, `commit`, `push_repo`, or `publish`.** `spend_log_for` already
resolves under `places.ledger.parent`, which is under `places.queue` regardless of whether `queue` is
a repository root or a subdirectory — this is D033's Trail amendment ("spend follows the work"),
and it was already true in the code before this change; nesting does not require touching it.
`commit()` only ever computes paths `relative_to(repo)` and calls git with that `repo` as `cwd` — a
subdirectory `cwd` is exactly as valid a `cwd` for git as a repository root, verified directly (see
Context). `publish()` still pushes exactly two places; see Non-Goals for why a third path or a
same-repo dedup is not built here.

**Why not fold nesting into `Places.local`'s own signature (e.g. an optional `queue_subdir` kwarg)?**
`Places.local`'s entire contract is "one path plays all four roles" — it is the shape every existing
caller assumes when it omits `--queue`/`--workspace`, and its docstring says so explicitly. Adding a
parameter that makes `queue != workspace` under a name that promises the opposite is the kind of
quietly-different behavior Article VII of the fleet constitution warns against; a distinctly-named
classmethod keeps `Places.local`'s contract intact.

## Risks / Trade-offs

**[Risk] A nested queue and workspace push twice to the identical remote branch.** →
**Mitigation:** none built; documented as harmless. `push_repo` is idempotent (a no-op push exits 0
with "Everything up-to-date"), so the cost is one redundant subprocess + network round trip per turn,
not a correctness issue. Collapsing this into one push would need `publish()` to compare the two
places' underlying repository roots (e.g. via `git rev-parse --show-toplevel`, or by reusing the
`queue_lock == workspace_lock` equality this change already establishes) and skip the second call —
a small, separable follow-on, not built here because it is speculative until a live run shows the
duplicate push actually costs something (Article VI: report, don't build unrequested optimizations).

**[Risk] `queue_subdir` collides with an existing directory the agent's own work creates.** →
**Mitigation:** `.factory` as a default name is chosen to be unlikely to collide and is the name
D033's own body uses (`a2web/.factory/…`); a caller with a real collision can pass a different
`queue_subdir`. Not otherwise guarded — no existing code guards `Places.local`'s ledger path against
collision with agent-created files either.

**[Risk] A workspace whose `.factory/` is `.gitignore`d silently loses every queue commit.** →
**Mitigation:** not guarded by this change. `commit()` already silently drops any path that does not
exist on disk after `git add`, and a gitignored path would simply never be added; this is the same
class of silent failure `guard transcript ignore with ledger` (an already-archived change) fixed for
the ledger under `Places.local`. Worth a follow-up if the nested shape starts real use, named here
rather than fixed speculatively.

**What this change does not prove:** it proves the mechanics (pick, claim, commit, ledger, spend row,
lock collapse) work for a nested queue in an ordinary git repository. It does not prove a *foreign*
workspace (a real `a2web` checkout, `.factory/` freshly created, agent actually invoked) behaves the
same way — that is `scripts/run_a2web_turn.py`'s job, and it is explicitly out of scope (this
change's dispatch: not migrating or wiring `factory-state`).
