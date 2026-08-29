## Why

K D033 ("the queue is the workspace; the runner holds only the key and the money") rules that each
workspace's backlog items live inside that workspace's own repository, so two concurrent turns against
*different* workspaces can never pick the same item and both pay for it — `pick()` is deterministic
and has no workspace filter (its own docstring: two turns picking the same item is resolved by the
claim, not by ordering), which is true for which record lands and false for who paid, since both
agents already ran under a shared central queue. `Places` already lets `queue` and `workspace` be
separate paths (`turn-places` spec, built for D026's private-queue/public-workspace shape), but that
support assumes each is a full repository with its own `.git`. D033's shape is a third one: `queue`
nested *inside* `workspace`'s own repository (`a2web/.factory/…`), not a repository of its own — and
constructing `Places` that way today points the queue lock at a `.git` directory that does not exist.

## What Changes

- Add `Places.nested(workspace, queue_subdir=".factory")`, a classmethod alongside `Places.local` for
  the shape where the queue is a subdirectory of the workspace's own repository rather than a
  repository of its own. Both `queue_lock` and `workspace_lock` resolve to the workspace's real
  `.git`-backed lock file (one tree, one lock), matching how `Places.local` already collapses the two
  locks when `queue == workspace`.
- Fix `runtime.loop._places_for` (the `--queue`/`--workspace` CLI resolution) to detect a nested queue
  (`queue` resolves inside `workspace`) and key both locks off the workspace, instead of assuming
  `queue` is its own repository root.
- No change to `commit()`, `push_repo()`, `publish()`, or `spend_log_for()` — verified that a
  nested queue commits and pushes correctly today because git resolves pathspecs and pushes relative
  to the enclosing repository regardless of which subdirectory `cwd` is set to, and `spend_log_for`
  already resolves under `places.queue` (D033's Trail amendment — "spend follows the work" — is
  already what the code does).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `turn-places`: adds the nested-queue-inside-workspace shape as a third configuration of the four
  roles, alongside "one location for all four" and "queue and workspace as two independent
  repositories."

## Impact

- `src/yosefactory/runtime/turn.py` — `Places.nested` classmethod.
- `src/yosefactory/runtime/loop.py` — `_places_for` nested-detection fix.
- `tests/runtime/` — end-to-end coverage: an item under `<workspace>/.factory/` picked, claimed,
  worked, and committed, with both locks proven to collapse to one file.
- Does **not** touch `factory-state`'s workflow or migrate its six existing items (out of scope,
  per dispatch — that repository belongs to the director).
