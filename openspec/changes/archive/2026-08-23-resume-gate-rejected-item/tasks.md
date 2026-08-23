## 1. Scheduler

- [x] 1.1 `runtime/turn.py::eligible()` admits `doing` whose most recent event (`item.records[-1]`)
      is `gate_rejected`, alongside the existing `ready` case.
- [x] 1.2 `take_turn`'s claim step branches: a `doing` target resumes the existing lease
      (`attempt`/`owner` read from `backlog.lease()`) and appends no `claimed`/`started`/commit; a
      `ready` target claims fresh exactly as today.
- [x] 1.3 Update the stale comment at the old claim step ("`target` is always `ready` here") to
      describe both branches.

## 2. Tests — new/updated coverage in `tests/runtime/test_turn_cycle.py`

- [x] 2.1 New test: a gate-rejected item is retried on the very next turn, inside its lease, with no
      manual reclaim — asserts the executor was called, exactly one `claimed` event exists in the
      item's log, `attempt` is unchanged, and `owner` on the resumed turn's new records matches the
      lease's existing owner.
- [x] 2.2 Update `test_a_gate_rejection_reaches_the_item_and_the_next_turns_context`: remove the
      manual `reclaimed` append/commit workaround now that the second turn picks the item up
      directly; keep its frame/context assertions.
- [x] 2.3 New test: an item whose gate always rejects still reaches `poison` within `max_attempts`,
      driven end-to-end through repeated daily wakes (`take_turn(..., now=...)`), demonstrating the
      fast path this change adds does not weaken the existing `reclaim_expired` bound.

## 3. Spec + write-back

- [x] 3.1 `openspec validate resume-gate-rejected-item --strict` passes.
- [x] 3.2 `make check` passes.
- [x] 3.3 Archive; confirm `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows only additive
      changes inside the two blocks declared MODIFIED above.
- [x] 3.4 Report the corrected S236 framing and the design.md tradeoff back to the director for
      write-back against S236/ADR-0015 (worker does not run `capture.py`/`wire.py` itself).
