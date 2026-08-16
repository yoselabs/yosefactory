# turn

Write exactly one JSON object to the path given as `proposal_path`, then stop.

```json
{"event": "<name>", "...": "the fields that event carries"}
```

One event. Do not set `event_id`, `ts` or `actor` — the caller writes those.
Do not edit anything under `backlog/`; the caller appends your event for you.
Report what happened; do not decide what happens next.

If you could not do the work, propose the event that says so rather than an
optimistic one.

A planning turn may write a JSON list of `created` events instead of one object.
