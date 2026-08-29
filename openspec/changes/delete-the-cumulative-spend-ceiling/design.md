## Two places explore overturned the dispatch (Article VII)

**1. `spend.total_since` stays.** The dispatch that opened this change listed it among the five
things to delete, on the reasoning that it exists only to serve the cumulative ceiling. It does
not: it has a second, pre-existing caller — `tests/conftest.py::pytest_sessionfinish`, which prints
"live spend this session" after `make test-live`, summing rows since the pytest session started.
That use has nothing to do with the loop's cumulative ceiling and is not touched by D034 at all —
it is per-session observability over the same per-run rows D034 explicitly keeps. The
`claude-executor/spend-ledger` spec already documents `total_since` this way: *"remains the default
for `spend.record`/`spend.total_since` when no `Places` is in view — a direct import, a REPL, or
this package's own `make test-live` session."* Deleting the function to satisfy this change would
break a caller this change has no mandate over. What is actually dead is one caller
(`loop.spent_so_far`), not the function itself.

**2. `LoopReport.spend_usd` stays, computed inline.** `spent_so_far()` was a closure over
`spend.total_since(start_moment, resolved_spend_log)`, called from two sites: the cumulative-ceiling
check (deleted) and the `MAX_ITERATIONS` return (kept — it is the "what did this loop invocation
spend" figure `main()` prints to stdout, which is D034's own "per-run" report, not the ceiling).
With only one call site left, the named closure is deleted per the dispatch and the one remaining
call is inlined at its return statement — same computation, no ceiling semantics attached to it.

## `scheduled_main` — kept, not collapsed

The dispatch asked whether `scheduled_main` still has a reason to exist once `--spend-ceiling-usd`
is gone, since its docstring names that flag as most of its point. Reading `main(unattended=...)`:
`unattended` gates three independent things, not one —

1. `--spend-ceiling-usd` required (**deleted by this change**)
2. `IsolationPolicy`: `isolated=False, workspace_scoped=True` instead of `isolated=True` — the
   posture that lets an unattended run actually act with nobody present to approve a tool prompt
3. `places.publish_workspace`/`publish_queue` default to declined unless `--publish` is given
   (D022 §2's push-grant boundary)

Losing (1) leaves (2) and (3) untouched, and both are real, load-bearing differences between a
person at a terminal and a scheduler with nobody watching — collapsing `scheduled_main` into `main`
would mean either giving every interactive invocation the workspace-scoped isolation posture and
the declined-publish default (wrong: D022 already carved that out for the human-present case), or
losing those two protections for the scheduled path (worse). `scheduled_main` survives as exactly
what it already was minus one required argument — a thin `main(argv, unattended=True)` — and its
own docstring is updated to stop naming the now-deleted flag as its reason to exist.
