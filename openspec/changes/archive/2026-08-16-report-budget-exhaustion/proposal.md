# report-budget-exhaustion

## Why

`classify` branches on `error_max_turns` and has no branch for `error_max_budget_usd`, so a run that
stopped because it ran out of budget falls through to the last line and is recorded as
`task_error`.

That is the misfiling `rate_limit` has its own outcome to prevent, one flag along, and §7b rule 3
forbids folding it into a generic failure. **`task_error` is worse here than no answer at all**: a
null invites the question, a wrong kind answers it — and answers it in the direction that sends
someone to debug a factory that was merely starved.

Nothing downstream can repair it. A consumer handed `TASK_ERROR` has no way back to the distinction,
so a faithful mapping at the record boundary would faithfully record a lie.

The fix is not new plumbing. The field is already flowing:

- the binary reports the stop **twice** — `subtype: "error_max_budget_usd"` and
  `terminal_reason: "budget_exhausted"`;
- `terminal_reason` is present on **every** terminal event (`"completed"` on a healthy run);
- it has been in this repository's own test fixture since that fixture was captured, unread.

Measured against `claude 2.1.225`: `--max-budget-usd 0.02` on a long generation → exit 1, a complete
terminal event, both fields set, `total_cost_usd 0.048`.

## What Changes

- **`classify` returns `RunOutcome.BUDGET_EXHAUSTED`** for a terminal event naming budget exhaustion,
  read from either field the binary sets, with no failure kind — exhaustion is the outcome, not a
  kind of breakage.
- **`terminal_reason` is read for the first time.** Only for this one stop.

## Non-goals

- **No rewrite of the classification path onto `terminal_reason`.** Which vocabulary is authoritative
  — `subtype` or `terminal_reason` — is a larger question that deserves its own proposal. Recorded
  here so a successor inherits the question rather than the silence: the binary now populates two
  overlapping vocabularies on every terminal event, and this change reads the second one only where
  the first has no answer at all.
- **No cost-ceiling enforcement.** `--max-budget-usd` is not emitted by anything. It also bounds the
  turn that crossed the line rather than the next one — measured 2.4× overshoot — so it is a detector
  rather than a ceiling, and describing it as a ceiling would mis-sell it.

## Capabilities

### Modified Capabilities
- `claude-executor/terminal-verdict`: budget exhaustion is its own outcome, read from the structured
  fields that report it.

## Impact

- **`src/yosefactory/executor/stream.py`** — one branch, two constants, one docstring line.
- No behaviour change for any run that did not exhaust a budget.
