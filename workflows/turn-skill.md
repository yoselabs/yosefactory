# turn

Write exactly one JSON object to `proposal_path`, then stop.

```json
{"event": "<name>", "...": "..."}
```

One event. Do not set `event_id`, `ts` or `actor` — the caller writes those.
Check the vocabulary for required fields; a proposal missing one is refused, not defaulted.
Do not edit the caller's own bookkeeping yourself; it appends your event.
Commit your own work first — explicit paths, never `git add -A` — or `done` is refused.
Report what happened; do not decide what happens next.

If you could not do the work, propose the failing event, not an optimistic one.

A planning turn may write a JSON list of `created` events instead.
