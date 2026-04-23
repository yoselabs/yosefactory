"""StageOutcome + InlineComment — structured result of a stage handler.

Architecture vision §7.2. ``StageHandler.execute()`` returns a
``StageOutcome``; the outcome is what ``effects()`` (P3) reads to emit
side effects, and what dispatch uses for routing decisions.

``InlineComment`` is the N1 payload — per-line review comments that
post back to GitHub as a native code review, not an aggregate comment.
Lands here in P1-style as a pure type; the REVIEW handler emits these
in P2 step 6, and the `GitHubReviewAdapter.post_inline_comments` impl
lands in P2 step 4.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from a2sdlc.domain.models import StageName, StageStatus


class InlineComment(BaseModel):
    """A single line-level PR review comment.

    Maps to GitHub's review-comments shape
    (``POST /repos/.../pulls/{n}/reviews``, ``comments[]`` array).

    Fields match the GitHub API as closely as is reasonable so the
    adapter layer is a thin translation.

    - ``file`` — path relative to repo root, as it appears in the PR diff.
    - ``line_start`` / ``line_end`` — 1-indexed line numbers in the file.
      When ``line_start == line_end``, the comment targets a single line.
    - ``body`` — comment text (markdown ok).
    - ``side`` — which side of the diff to anchor on.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str
    line_start: int
    line_end: int
    body: str
    side: Literal["LEFT", "RIGHT"] = "RIGHT"


class StageOutcome(BaseModel):
    """Structured result of a ``StageHandler.execute()``.

    Carries everything routing + effects (P3) need to know about the run:

    - ``status`` — the agent's reported StageStatus (or None for MERGE
      which is deterministic).
    - ``output_text`` — the agent's final textual output (for the ticket
      comment; stripped of any status block).
    - ``inline_comments`` — per-line review comments (N1). Empty for
      non-REVIEW stages and for REVIEW runs that did not produce comment
      payloads.
    - ``stats`` — optional ``StageRunStats`` (from ``domain.stats``) with
      cost / tokens / duration / turns for metrics. Kept as ``Any`` here
      because it is a dataclass, not a Pydantic model; validation is
      structural at the boundary.
    - ``merged`` — True iff this was a successful MergeStage run. Null
      for AI stages.
    - ``blocked`` — True iff execute() decided this run should block the
      ticket (agent failure, no-status-block, mid-flight error). Distinct
      from ``preconditions()`` returning a BlockReason: preconditions
      blocks BEFORE work starts, ``blocked`` means work started and
      couldn't complete. P3 replaces this with a ``MarkBlocked`` Effect
      variant in the effects() ADT.
    - ``error`` — short tag describing why ``blocked`` is set, or the
      agent's surfaced error. ``None`` on the happy path. Flows into
      ``stage_end`` telemetry. P3 moves this into the ``CommentError``
      Effect variant.
    - ``next_stage_hint`` — stage the handler suggests routing to next.
      Null means "use the transition table" (the normal case). Non-null
      lets a handler carry explicit hand-off info (rare — used by N2
      EPIC_ORCHESTRATE once it lands).
    - ``prepared_effects`` — transitional carrier (P3). ``execute()``
      precomputes the full effect list because the data for it (final
      comment body, TicketState, metrics) is produced mid-execution.
      ``effects(ctx, outcome)`` returns this list unchanged. A later
      phase can normalize this by enriching StageOutcome with enough
      structured fields for ``effects()`` to compute the list purely.
    """

    # ``stats`` is a StageRunStats dataclass at runtime; allow arbitrary
    # types so Pydantic doesn't try to validate it as a BaseModel.
    # ``prepared_effects`` holds ``Effect`` dataclasses, also non-Pydantic.
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    status: StageStatus | None = None
    output_text: str = ""
    inline_comments: list[InlineComment] = Field(default_factory=list)
    stats: Any | None = None
    merged: bool | None = None
    blocked: bool = False
    error: str | None = None
    next_stage_hint: StageName | None = None
    prepared_effects: list[Any] = Field(default_factory=list)


__all__ = ["InlineComment", "StageOutcome"]
