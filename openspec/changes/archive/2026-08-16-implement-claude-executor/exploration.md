# Explore — implement-claude-executor

Promotion: **D021** (thin wrappers implementing one interface so the core is executor-agnostic;
agent runs isolated), **architecture.md §7b** (the executor interface, and its four rules),
**S182** (three endings), **S185** (shared-index commits), **S187** (`dirty` and the observer
inside the observed).

Status: **explore done, blocked on one decision** (§4 below). Nothing implemented yet.

## 1. What the dispatch asked for

```
run(frame, workspace, limits) -> RunResult
  RunResult{ outcome, usage, transcript_path, exit_code, dirty }
  outcome in success | budget_exhausted | turn_limit | needs_approval
          | refused | cancelled | failed(auth|rate_limit|crash|bad_output|task_error)
```

Four non-negotiable rules, restated so a successor does not have to fetch them:

1. The exit code is never the verdict. The verdict is a mandatory terminal structured event.
   No terminal event means failure, even on exit 0. `143` maps to `cancelled`.
2. A turn ending is not the run ending. Keying on the wrong one truncates a run and it reads
   as a short success.
3. `rate_limit` is its own outcome, never folded into a generic failure. A starved factory
   must not look like a broken model.
4. No executor has a cost ceiling or a wall clock. Both belong to the harness, already built
   in `runtime/supervise.py`. Wire to them; do not rebuild them.

## 2. Measured against the real binary

`claude` 2.1.225. One bounded invocation, `--output-format stream-json --verbose
--permission-mode manual --strict-mcp-config`, in a scratch directory outside the repo.

Event types observed, in order:

```
system   | init               capabilities, cwd, memory_paths, mcp_servers, model,
                              permissionMode, plugins, session_id, skills, slash_commands, tools
rate_limit_event              rate_limit_info
assistant                     message, parent_tool_use_id, request_id
system   | post_turn_summary  needs_action, status_category, status_detail, summarizes_uuid
result   | success            api_error_status, duration_api_ms, duration_ms, is_error,
                              modelUsage, num_turns, permission_denials, result, stop_reason,
                              subtype, terminal_reason, total_cost_usd, ttft_ms, usage
```

Terminal event, field values on a clean run: `is_error: false`, `subtype: "success"`,
`stop_reason: "end_turn"`, `terminal_reason: "completed"`, `num_turns: 1`,
`permission_denials: []`, `api_error_status: null`.

### What this settles

- **Rule 1 has a real anchor.** `type: "result"` is the terminal event, and it carries three
  verdict-bearing fields rather than one: `subtype`, `stop_reason`, `terminal_reason`.
- **Rule 2 has a measured mapping on this lane.** `system|post_turn_summary` is the turn
  ending; `result` is the run ending. S182 derived this contract from pi; it holds here.
- **Rule 3 has a native signal.** `rate_limit_event` is its own stream event type carrying
  `rate_limit_info` — the outcome is observable, not inferred from an error string.
- **`needs_approval` has a native signal.** `permission_denials` on the terminal event.
- **Isolation is verifiable, not merely asserted.** `system|init` reports `memory_paths`,
  `mcp_servers`, `skills`, `plugins` and `permissionMode`. Asserting isolation from the
  stream is strictly stronger than trusting that `--settings` took effect.

### What this falsifies

- **There is no `--max-turns` flag in 2.1.225.** The full `--help` was searched. The turn
  ceiling has no native control on the Claude lane; it is harness-only, which is what
  `govern()` already assumes. The archived `add-run-guardrails` proposal states
  "`--max-turns` stays" under Non-goals — that is no longer true of this binary.
- **`num_turns` appears only in the terminal event.** A live turn counter must count
  `post_turn_summary` events as they stream; it cannot read `num_turns` until the run is over,
  by which point the ceiling is moot.
- **The "~1-token canary" of §7b is not cheap.** The probe billed **$0.2468**: 2 input tokens
  and 4 output tokens, against **24,607 cache-creation tokens** at the 1-hour TTL. A per-run
  preflight is a real cost line, not a rounding error. Write-back candidate against §7b.

## 3. The seams this change must fit

- `runtime/supervise.py::govern(argv, *, repo, runs_dir, run_id, guard, turn_ceiling,
  isolated, turns_taken, verdict, poll_seconds) -> TurnRecord`. `turns_taken` and `verdict`
  are the two callables this change is meant to supply. `govern` computes `dirty` itself and
  writes the `TurnRecord`; `SUPERVISOR_OWNED = ("dirty",)` means this change never supplies it.
- `runtime/isolation.py::IsolationPolicy` — policy only, deliberately spawns nothing.
  Translating it into invocation arguments is this change's job. `uses_bare_mode` is always
  false and asserted by test: `--bare` does not read `CLAUDE_CODE_OAUTH_TOKEN`, so on a
  subscription bare mode and authentication are mutually exclusive.
- `protocol/turn.py::Outcome` — exactly four values, frozen: `advanced | blocked |
  nothing-ready | failed`. `govern(verdict=...)` is typed to this enum.

## 4. Blocked on — decision owed by the director

**`govern()` does not capture the child's stdout.** `supervise.py:127` is
`subprocess.Popen(argv, cwd=repo)`, so the child inherits the parent's stdout and the terminal
`result` event — the verdict under rule 1 — is unreachable. `turns_taken` and `verdict` have
nothing to observe. The integration receipt this change owes cannot be produced as the code
stands.

`runtime/` is another worker's scope, so this change does not edit it unasked (Article IV).
Options put to the director, recommendation first:

1. Add `stdout: Path | None = None` to `govern()`. Additive; the default preserves current
   behaviour and every existing `test_supervise.py` case.
2. Dispatch that parameter to the owner of `runtime/supervise.py`; this change waits.
3. Wrap argv in a shell redirect. **Rejected on analysis** — `_terminate` would then signal
   the shell rather than the agent, destroying the grace window in which the agent flushes
   its own verdict.

## 5. Open conflict — ruling owed, does not block

The dispatch's `RunResult.outcome` has roughly ten values. `protocol.Outcome` has four and is
frozen. The executor vocabulary is vendor-shaped and will change as vendors change, so by the
C2 test it is soft and belongs in `executor/`, mapping down to the four at the `govern` seam.

The consequence needs a ruling: **rule 3 forbids folding `rate_limit` into a generic failure,
but a `TurnRecord` can only say `failed`.** A starved factory and a broken model are
indistinguishable in the record — the exact failure rule 3 exists to prevent. `TurnRecord.note`
is free text and unqueryable. A real fix touches `protocol/`, which is another worker's scope.

Interim plan unless overruled: type it correctly in `RunResult`, carry it in `note`, and record
the contradiction against the corpus rather than papering over it.

## 6. Not overturned

The dispatch stands. §7b names a wider interface (`resolveVersion`, `capabilities`,
`preflight`, `run`); the dispatch scopes this change to `run`. Held to `run` plus a version
pin, because §2 shows behaviour is version-specific and §7b rule 4 forbids a capability claim
without a passing conformance test.
