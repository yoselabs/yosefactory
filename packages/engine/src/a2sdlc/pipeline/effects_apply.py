"""Effects interpreter — apply a ``list[Effect]`` against live adapters.

The seam between handlers (pure) and side effects (I/O). Handlers
return ``list[Effect]`` from ``effects()``; this module applies them
in list order against the adapters carried on ``DispatchContext``.

V1.0 arms without an interpreter branch are registered in
``domain.effects`` for forward-compat but raise ``NotImplementedError``
if emitted — that's deliberate. Silent drops would hide handler bugs.
Later phases add the missing arms alongside their callers.

Ordering contract: effects apply strictly in list order, short-circuit
on first exception. Handlers must order effects so that a partial
failure leaves the ticket in a recoverable state (e.g. emit
``MarkBlocked`` before ``CommentFinalize`` so a failed comment write
doesn't strand the ticket "in-progress").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2sdlc.domain.effects import (
    AwaitHumanDecision,
    CommentFinalize,
    CommitAndPush,
    Effect,
    LogMetric,
    MarkBlocked,
    MarkDone,
    MarkNeedsInput,
    MergePR,
    PostInlineReview,
    PostReview,
    SetCurrentStage,
    StateWrite,
    StripRuntimeState,
    SyncBase,
    UpdatePRTitle,
)

if TYPE_CHECKING:
    from a2sdlc.pipeline.dispatch import DispatchContext


async def apply(ctx: "DispatchContext", effects: list[Effect]) -> None:
    """Apply each effect against ctx's adapters in list order.

    Per-run state (``ctx.pre``, ``ctx.comment``, ``ctx.pr_lifecycle``,
    ``ctx.run``) must be populated by dispatch before calling; arms
    reading them raise ``RuntimeError`` with a clear message otherwise.
    """
    for eff in effects:
        _apply_one(ctx, eff)


def _apply_one(ctx: "DispatchContext", eff: Effect) -> None:  # noqa: C901,PLR0912
    match eff:
        case MarkBlocked(reason=reason):
            ctx.work.mark_blocked(_key(ctx), reason)

        case MarkDone():
            ctx.work.mark_done(_key(ctx))

        case MarkNeedsInput():
            ctx.work.mark_needs_input(_key(ctx))

        case AwaitHumanDecision(kind=kind, reason=reason):
            # V1.0: structured log only. The dispatch-level pause signal
            # is read directly from the effect list at the translator in
            # pipeline/dispatch.py. Future phases extend this arm —
            # dashboard notification, Slack ping, SLA tracking — without
            # changing the handler-side emission.
            ctx.logger.info(
                "dispatch.await_human",
                extra={"kind": kind, "reason": reason, "ticket": _key(ctx)},
            )

        case SetCurrentStage(stage=stage):
            ctx.work.set_current_stage(_key(ctx), stage)

        case CommentFinalize(body=body):
            _require(ctx.comment, "comment").finalize(body)

        case PostReview(pr_number=pr, verdict=verdict, body=body):
            _require(ctx.pr_lifecycle, "pr_lifecycle").post_review(pr, body, verdict)

        case PostInlineReview(pr_number=pr, comments=comments):
            ctx.review.post_inline_comments(pr, comments)

        case MergePR(pr_number=pr, method=method):
            _require(ctx.pr_lifecycle, "pr_lifecycle").merge(pr, method)

        case SyncBase(base=base):
            ctx.git.sync_with_base(base)

        case StripRuntimeState():
            # Best-effort — matches the pre-migration inline try/except.
            try:
                ctx.git.strip_runtime_state()
            except Exception:  # noqa: BLE001
                ctx.logger.warning("dispatch.state_strip_failed", exc_info=True)

        case UpdatePRTitle(pr_number=pr, title=title):
            _require(ctx.pr_lifecycle, "pr_lifecycle").update_title(pr, title)

        case StateWrite(state=state):
            pre = _require(ctx.pre, "pre")
            pre.state_mgr.write_state(state)

        case CommitAndPush(message=message, paths=paths):
            # Best-effort — matches today's handler behavior. A push
            # failure is logged at warning level; the pipeline continues.
            try:
                ctx.git.commit_artifacts(message, list(paths))
                ctx.git.push()
            except Exception:  # noqa: BLE001
                ctx.logger.warning("dispatch.commit_push_failed", exc_info=True)

        case LogMetric(key=key, value=value):
            _require(ctx.run, "run").log_metric(key, value)

        case _:
            msg = (
                f"Effect {type(eff).__name__} has no interpreter arm. "
                "Register one in pipeline/effects_apply.py before emitting."
            )
            raise NotImplementedError(msg)


def _key(ctx: "DispatchContext") -> str:
    return _require(ctx.pre, "pre").event.key


def _require(value, name):  # type: ignore[no-untyped-def]
    if value is None:
        msg = f"effects_apply requires ctx.{name} to be populated by dispatch"
        raise RuntimeError(msg)
    return value


__all__ = ["apply"]
