"""Pipeline middleware — cross-cutting wrappers around the stage-attempt unit.

Vision §7.4 middleware onion. Each middleware is a higher-order
function that takes a ``StageAttempt`` and returns a new
``StageAttempt`` with the wrapping behavior applied. Composition reads
as the onion literally:

    stack = with_idempotency(with_telemetry(run_stage))
    return await stack(ctx, intent)

Middleware wraps the "we've resolved intent, now do the run" unit —
**not** the whole ``dispatch()``. Idempotency needs ``intent`` to exist
(it reads ``intent.state_mgr``), and telemetry only opens a session
for actually-attempted stages. The honest boundary is the stage-attempt.

P5 ships two middleware — ``with_idempotency``, ``with_telemetry``.
Future phases add retry / logging / etc. as concrete call sites appear.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult

StageAttempt = Callable[[RunContext, RunIntent], Awaitable[DispatchResult]]
Middleware = Callable[[StageAttempt], StageAttempt]


__all__ = ["Middleware", "StageAttempt"]
