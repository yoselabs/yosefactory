"""StageHandler Protocol — the Strategy type for stages.

Architecture vision §7.2 load-bearing type #2. Every stage conforms:

- ``name`` / ``valid_statuses`` — static metadata, already on today's
  stage classes.
- ``preconditions(ctx)`` — **pure** — returns a ``BlockReason`` or
  ``None``. Today's preflight / breaker logic migrates here in P2
  steps 5-8.
- ``execute(ctx)`` — the I/O boundary. The only async method. Today's
  ``execute_ai_stage`` / ``execute_merge`` bodies migrate here.
- ``effects(ctx, outcome)`` — **pure** — returns ``list[Effect]``. In
  P2 this returns an empty list; P3 defines the real ``Effect`` ADT
  and shifts side-effect emission from ``execute()`` into this method.

The ``ctx`` type (``RunContext``) is not yet formalized in the codebase.
P2 threads the existing ``DispatchContext`` through ``execute()`` as
the ctx-equivalent; P4 introduces a narrower ``RunContext`` and the
Protocol's ``execute(ctx)`` signature tightens.

Step 2 of P2. No stages adopt it yet — steps 5-8 do. Lands the shape
early so reviewers can see where P2 is going.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from a2sdlc.domain.block_reason import BlockReason
from a2sdlc.domain.effects import Effect
from a2sdlc.domain.models import StageName, StageStatus
from a2sdlc.domain.stage_outcome import StageOutcome

if TYPE_CHECKING:
    # DispatchContext is the ctx today; P4 narrows it to RunContext.
    # Import guarded to avoid import cycles while the migration is mid-flight.
    from a2sdlc.pipeline.dispatch import DispatchContext as _RunContext

    Context = _RunContext
else:
    Context = Any


class StageHandler(Protocol):
    """Every stage conforms to this shape (P2 onward).

    Classes are structurally typed (Protocol) so stages can be plain
    classes without explicit inheritance. Adding a stage = one new
    class + one registry entry; no edits elsewhere.
    """

    name: StageName
    valid_statuses: frozenset[StageStatus]

    def preconditions(self, ctx: Context) -> BlockReason | None:
        """Pure precondition check — return BlockReason to block, None to proceed."""

    async def execute(self, ctx: Context) -> StageOutcome:
        """I/O boundary — do the work and return a structured outcome."""

    def effects(self, ctx: Context, outcome: StageOutcome) -> list[Effect]:
        """Pure mapping from outcome to list of Effects.

        Return type tightened to ``list[Effect]`` in P3 step 3 alongside
        the interpreter wire-up. Per-handler migration (P3 steps 4–7)
        populates these lists; until then each handler returns ``[]``.
        """


__all__ = ["StageHandler"]
