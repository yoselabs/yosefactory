"""Effect ADT — side effects as data.

Architecture vision §7.2 load-bearing type #2. Handlers return a pure
``list[Effect]`` from ``effects(ctx, outcome)``; a separate interpreter
applies effects against adapters. Separating the description of a side
effect from its execution is the "big unlock" for the engine —
effects are logged, replayable, and auditable (architecture vision §P6).

V1.0 arm scope comes from RFC-0001 §Data model. Arms are grouped into:

- **Session lifecycle** — comment, PR, review, label, state transitions.
- **Git** — commit/push, base cleanup.
- **Control flow** — pipeline transitions.
- **Quality / evaluation** — metrics, artifacts, quality gates.

Each arm is a frozen dataclass. The ``Effect`` alias is their union,
suitable for exhaustive ``match`` in the interpreter.

Arms registered here but **without an interpreter arm yet** are
forward-compat seams — they exist so handlers in later phases can emit
them without schema churn. Unhandled variants raise in the interpreter
so additions are detected, not silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from a2sdlc.domain.models import StageName, TicketState
    from a2sdlc.domain.stage_outcome import InlineComment


# ── Session lifecycle ────────────────────────────────────────────────


@dataclass(frozen=True)
class StateWrite:
    """Persist a new ``TicketState`` to session storage."""

    state: "TicketState"


@dataclass(frozen=True)
class CommentStart:
    """Open a fresh progress comment for the stage.

    Registered for forward-compat (P6 moves comment lifecycle into
    effects). No interpreter arm in V1.0 — dispatch still opens the
    comment directly before handler.execute().
    """

    stage: "StageName"


@dataclass(frozen=True)
class CommentFinalize:
    """Finalize the active progress comment with ``body``."""

    body: str


@dataclass(frozen=True)
class CreateDraftPR:
    """Create a draft PR for ``branch`` targeting ``base``.

    Registered for forward-compat. Dispatch's ``_ensure_draft_pr``
    still handles this in V1.0.
    """

    branch: str
    base: str
    ticket_key: str


@dataclass(frozen=True)
class UpdatePR:
    """Update PR title / body.

    Registered for forward-compat; no interpreter arm in V1.0.
    """

    pr_number: int
    title: str
    body: str
    ticket_key: str


@dataclass(frozen=True)
class MergePR:
    """Mark PR ready and squash-merge it."""

    pr_number: int
    method: str = "squash"


@dataclass(frozen=True)
class PostReview:
    """Post a native PR review (APPROVE / REQUEST_CHANGES) with ``body``."""

    pr_number: int
    verdict: str
    body: str


@dataclass(frozen=True)
class PostInlineReview:
    """Post per-line review comments on a PR (N1).

    Empty ``comments`` is a valid no-op — mirrors the adapter Protocol.
    """

    pr_number: int
    comments: list["InlineComment"]


@dataclass(frozen=True)
class SetCurrentStage:
    """Transition the ticket's current-stage marker to ``stage``."""

    stage: "StageName"


@dataclass(frozen=True)
class MarkBlocked:
    """Flag the ticket as blocked with ``reason`` (for platform + audit)."""

    reason: str


@dataclass(frozen=True)
class MarkDone:
    """Flag the ticket as done (pipeline terminal, post-MERGE)."""


@dataclass(frozen=True)
class MarkNeedsInput:
    """Flag the ticket as awaiting human input (QUESTIONS status)."""


# ── Git ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CommitAndPush:
    """Commit ``paths`` with ``message`` and push to origin.

    Best-effort in V1.0 — matches today's handler behavior of swallowing
    push failures with a logged warning.
    """

    message: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class CleanupBase:
    """Cleanup base branch after merge.

    Registered for forward-compat; no interpreter arm in V1.0.
    """

    base: str


@dataclass(frozen=True)
class SyncBase:
    """Fetch + merge ``base`` into the current branch (pre-merge sync).

    Part of the MERGE stage's pre-merge sequence (P3 step 7). Ensures
    the PR head is up-to-date with base before the squash.
    """

    base: str


@dataclass(frozen=True)
class StripRuntimeState:
    """Wipe runtime state (``.a2sdlc/state/``) before merge.

    Best-effort in V1.0 — the interpreter logs + continues on failure,
    matching the pre-migration inline try/except pattern.
    """


@dataclass(frozen=True)
class UpdatePRTitle:
    """Set the PR title before merge so the squash commit reflects ticket intent.

    Distinct from ``UpdatePR`` which also sets body + ticket_key. Kept
    narrow because the merge flow only needs title promotion.
    """

    pr_number: int
    title: str


# ── Control flow ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Transition:
    """Signal the next stage (or ``None`` for wait-for-human).

    Registered for forward-compat. Dispatch still reads
    ``next_stage_hint`` off the StageOutcome in V1.0.
    """

    next: "StageName | None"


# ── Quality / evaluation ─────────────────────────────────────────────


@dataclass(frozen=True)
class LogMetric:
    """Log a numeric metric on the current run handle."""

    key: str
    value: float


@dataclass(frozen=True)
class LogArtifact:
    """Log an artifact path to the current run handle.

    Registered for forward-compat; no interpreter arm in V1.0.
    """

    path: str


@dataclass(frozen=True)
class RunQualityGate:
    """Run a quality-gate command and veto (via MarkBlocked) if it fails.

    Registered for forward-compat; no interpreter arm in V1.0. The N4
    partial (secrets scan) uses ``RunSecretsScan`` instead.
    """

    command: str


@dataclass(frozen=True)
class RunSecretsScan:
    """Run the N4 secrets-scan hook; veto via MarkBlocked on findings.

    Registered for forward-compat; no interpreter arm in V1.0. Lands
    with the N4 P3-follow-up work.
    """

    paths: tuple[str, ...]


# ── Union type ───────────────────────────────────────────────────────

Effect = (
    StateWrite
    | CommentStart
    | CommentFinalize
    | CreateDraftPR
    | UpdatePR
    | MergePR
    | PostReview
    | PostInlineReview
    | SetCurrentStage
    | MarkBlocked
    | MarkDone
    | MarkNeedsInput
    | CommitAndPush
    | CleanupBase
    | SyncBase
    | StripRuntimeState
    | UpdatePRTitle
    | Transition
    | LogMetric
    | LogArtifact
    | RunQualityGate
    | RunSecretsScan
)


__all__ = [
    # Session lifecycle
    "StateWrite",
    "CommentStart",
    "CommentFinalize",
    "CreateDraftPR",
    "UpdatePR",
    "MergePR",
    "PostReview",
    "PostInlineReview",
    "SetCurrentStage",
    "MarkBlocked",
    "MarkDone",
    "MarkNeedsInput",
    # Git
    "CommitAndPush",
    "CleanupBase",
    "SyncBase",
    "StripRuntimeState",
    "UpdatePRTitle",
    # Control flow
    "Transition",
    # Quality / evaluation
    "LogMetric",
    "LogArtifact",
    "RunQualityGate",
    "RunSecretsScan",
    # Union
    "Effect",
]
