## Context

See `proposal.md` for the finding and the three argued decisions. Relevant current state:

- `Places` (`runtime/turn.py`) is a frozen `slots=True` dataclass with five required fields, all
  supplied by keyword at every call site in production code and tests (`Places.local`,
  `test_turn_cycle.py`'s `places()` helper, `test_turn_integration.py`'s `places()` helper). Appending
  trailing fields with defaults is backward compatible with every existing constructor call.
- `publish(places, record)` is called unconditionally at three sites inside `take_turn` (the
  nothing-ready path, the planning path, the claimed-item path), each after `_finish` has already
  committed the turn record. `publish` itself already gates on `record.outcome is Outcome.ADVANCED`
  and no-ops otherwise — the new gate composes with that one, not instead of it.
- `push_repo(repo)` is a free function taking only a `Path`; it has no knowledge of `Places` or of any
  caller intent, and stays that way — the decision belongs in `publish`, which already holds both
  `Places` and the ordering logic (workspace before queue).

## Goals / Non-Goals

**Goals:**
- A caller can decline publication for either place independently, before the turn runs.
- The default is unchanged for every existing caller.
- A declined place is reported distinctly from a place with no remote, checkable by `status` alone.

**Non-Goals:** see `proposal.md`.

## Decisions

**Field names: `publish_queue`, `publish_workspace`** — matching `Places`'s own field names
(`queue`, `workspace`) rather than a nested value object. `Places` is already a flat bag of five
`Path`s; two more flat `bool`s follow the shape already established rather than introducing a second
grouping construct for two fields.

```python
@dataclass(frozen=True, slots=True)
class Places:
    queue: Path
    ledger: Path
    queue_lock: Path
    workspace: Path
    workspace_lock: Path
    publish_queue: bool = True
    publish_workspace: bool = True
```

**`publish()`'s new shape** — the flag check replaces the unconditional `push_repo` call, not wraps
it, so a declined place's code path never touches `push_repo`:

```python
def publish(places: Places, record: TurnRecord) -> tuple[PublishResult, PublishResult] | None:
    if record.outcome is not Outcome.ADVANCED:
        return None
    workspace_result = (
        push_repo(places.workspace)
        if places.publish_workspace
        else PublishResult(repo=places.workspace, status="declined", detail="publication declined for this place")
    )
    queue_result = (
        push_repo(places.queue)
        if places.publish_queue
        else PublishResult(repo=places.queue, status="declined", detail="publication declined for this place")
    )
    for result in (workspace_result, queue_result):
        if result.status == "rejected":
            warnings.warn(f"publish: {result.repo} push rejected: {result.detail}", PublicationFailed, stacklevel=2)
    return workspace_result, queue_result
```

Ordering (workspace computed and returned before queue) is preserved exactly, satisfying
`turn-publication`'s existing "workspace publishes before queue" requirement whether or not either
place is declined.

**`PublishResult.status`'s docstring comment updated** to `# "pushed" | "skipped" | "rejected" |
"declined"` — a comment, not a type; nothing elsewhere in the codebase pattern-matches on the string
set exhaustively (`publish`'s own rejected-check is the only branch, and it is unaffected by a new
value it does not test for).

**No `Places.local` change.** `Places.local(repo)` continues to construct with the five original
fields; the two new fields take their defaults (`True`), so a single-repository turn publishes exactly
as it always has.

## Risks / Trade-offs

- **A caller that declines both places silently loses D014's own measurement instrument** if they
  forget to publish later by some other means. Not mitigated here — this change gives the caller a way
  to decline, not a way to be reminded to un-decline. The a2web dispatch's own plan (report the diff,
  the director takes the publish decision to Denis) is the human process that currently fills that
  gap; a mechanical reminder is future scope if the pattern recurs.

## Migration

None — two new fields with defaults matching current unconditional behaviour; no existing signature
changes in a breaking way.
