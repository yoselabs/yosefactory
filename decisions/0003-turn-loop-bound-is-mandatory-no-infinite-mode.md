# ADR-0003 — The turn loop's bound is mandatory; there is no infinite mode

**Status:** Accepted
**Date:** 2026-08-17
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a caller needs `run_loop` to run with no upper bound on turns or spend, and
can name a control other than `max_iterations`/`spend_ceiling_usd` that keeps an unattended,
self-chaining loop from spending without a human between iterations.

## Context

`add-turn-loop` (archived 2026-08-17) gave `runtime.turn.take_turn` its first caller that runs it
more than once without a person retyping the command — `runtime/loop.py::run_loop`. Before this
change, every "live" receipt in `tests/runtime/test_turn_integration.py` called `take_turn` exactly
once and stopped; nothing in the codebase had ever driven it in a loop.

S195 (P160) found nine mechanisms declared and never reached, one instance of "a typed field with
no writer is not a smaller version of a typed field." `add-turn-loop`'s own proposal names the same
shape one level up: a self-chaining loop is the first thing in this program capable of spending
money without a human between iterations, so its bound could not be an afterthought added once the
loop worked — it had to exist before the loop could self-chain at all.

## Decision

`LoopBound.max_iterations` is a required `int` with no default, validated `>= 1` in
`__post_init__`; there is no configuration, flag, or code path that constructs a `LoopBound`
without it, and no "run forever" mode exists anywhere in `runtime/loop.py`. `spend_ceiling_usd` is
optional — a loop whose only eligible turns are `nothing-ready` (which cost $0 by construction) has
nothing for a spend ceiling to bound, so `max_iterations` alone is sufficient for that case; when
set, it is checked against cumulative spend recorded in `ledger/spend.jsonl` since the loop
started.

The loop stops the first time either half of the bound holds (`StopReason.MAX_ITERATIONS` or
`StopReason.SPEND_CEILING`) — never both required, never neither checked.

## Consequences

- Every caller of `run_loop`/`main()`/`scheduled_main()` must supply `--max-iterations` (or the
  equivalent constructor argument); there is no way to omit it and get a default. The container's
  own `CMD` and the human-driven CLI both carry it explicitly.
- A loop that never has ready work costs $0 waiting for it — the `nothing-ready` path never starts
  an executor — so the bound does not force paid turns onto an idle backlog just to terminate.
- **Rejected alternative:** an optional bound defaulting to "unbounded" (mirroring
  `spend_ceiling_usd`'s own optionality). Rejected because the two fields are not symmetric: a
  turn without a spend ceiling still terminates on iteration count; a loop without *any* bound has
  no termination condition at all, and this is the first caller in the program capable of spending
  unattended.

## References

- `src/yosefactory/runtime/loop.py` — `LoopBound`, `run_loop`.
- `openspec/changes/archive/2026-08-17-add-turn-loop/proposal.md`, `design.md`.
- P160 S195 (typed field with no writer), `orchestration.md` Article XVI (the receipt question).
