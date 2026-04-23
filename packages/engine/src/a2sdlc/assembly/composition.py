"""``CompositionProfile`` — declarative wiring for one pipeline run.

Vision §7.5 composition profile. Names which adapters, subscribers,
and credential profile this run uses so ``cli/dispatch.py`` and
``cli/run_stage.py`` can share a single wiring path. P6 step 1 lands
the shape; later steps add the resolver, validator, and builders.

Slot choices:
- ``work`` — which tracker backs this run.
- ``review`` — PR / review backend.
- ``git`` — local clone vs. a throwaway branch checkout.
- ``progress_subscribers`` — tuple of subscriber names attached to
  ``ProgressState`` when the run starts.
- ``credential_profile`` — name of the auth strategy. ``"github_token"``
  today; ``"dual_app"`` is the N8 slot and raises at validation time
  until N8 wires real two-App execution.

The runner slot (``SdkStageRunner(effort=...)``) is deliberately not
modeled — V1.0 has one runner class; a second one earns the field.
Middleware order is likewise fixed by ``pipeline/dispatch.py`` per P5;
a ``profile.middleware`` slot re-appears when a caller needs to vary
it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from a2sdlc.domain.models import StageName
    from a2sdlc.domain.progress import ProgressState


@dataclass(frozen=True)
class CompositionProfile:
    """Frozen, hashable profile. Constructed by a resolver; consumed by builders."""

    work: Literal["github_issue", "workflow_input", "local_file"]
    review: Literal["github", "local_noop"]
    git: Literal["local", "local_branch"]
    progress_subscribers: tuple[str, ...]
    credential_profile: Literal["github_token", "dual_app"]


def resolve_composition_profile(
    env: Mapping[str, str],
    *,
    mode: Literal["dispatch", "run-stage"],
) -> CompositionProfile:
    """Resolve the profile from env + the invoking CLI subcommand.

    Three V1.0 resolutions:

    - ``mode="run-stage"`` → ``local-file`` profile. File-backed
      tickets, no-op review, scratch-branch git.
    - ``mode="dispatch"`` + ``DISPATCHER_URL`` set → ``ci-dispatcher``
      profile. Workflow-input work, GH review, local git, dispatcher
      event subscriber + console.
    - ``mode="dispatch"`` otherwise → ``ci-github-native`` profile.
      GH-issue work, GH review, local git, gh-comment subscriber.
    """
    if mode == "run-stage":
        return CompositionProfile(
            work="local_file",
            review="local_noop",
            git="local_branch",
            progress_subscribers=("gh_comment",),
            credential_profile="github_token",
        )
    if env.get("DISPATCHER_URL"):
        return CompositionProfile(
            work="workflow_input",
            review="github",
            git="local",
            progress_subscribers=("dispatcher_event", "console"),
            credential_profile="github_token",
        )
    return CompositionProfile(
        work="github_issue",
        review="github",
        git="local",
        progress_subscribers=("gh_comment",),
        credential_profile="github_token",
    )


def validate_profile(profile: CompositionProfile) -> None:
    """Assert legal combinations; raise on misconfiguration.

    Rules today:
    - ``workflow_input`` work requires the ``dispatcher_event``
      subscriber to be attached (comments otherwise silently drop).
    - ``credential_profile="dual_app"`` is the N8 slot and has no
      runtime wiring yet — raises ``NotImplementedError``.
    """
    if (
        profile.work == "workflow_input"
        and "dispatcher_event" not in profile.progress_subscribers
    ):
        msg = "workflow_input work adapter requires dispatcher_event subscriber"
        raise ValueError(msg)
    if profile.credential_profile == "dual_app":
        msg = "dual_app credential profile is N8 — not wired in P6"
        raise NotImplementedError(msg)


def build_adapters(
    profile: CompositionProfile,
    *,
    project_root: Path,
    session_id: str,
    stage: "StageName",
    ticket_path: Path | None = None,
    env: Mapping[str, str],
) -> tuple[Any, Any, Any]:
    """Return the ``(work, git, review)`` adapter triple for ``profile``.

    Thin delegator over ``adapters.factory``. The caller still owns
    runner construction because ``SdkStageRunner`` lives in ``pipeline/``
    which ``assembly/`` cannot import from.
    """
    from a2sdlc.adapters.factory import (  # noqa: PLC0415
        build_git_adapter,
        build_review_adapter,
        build_work_adapter,
    )

    work = build_work_adapter(
        profile.work,
        project_root=project_root,
        session_id=session_id,
        stage=stage,
        ticket_path=ticket_path,
        env=env,
    )
    git = build_git_adapter(profile.git, project_root=project_root)
    review = build_review_adapter(profile.review, project_root=project_root, env=env)
    return work, git, review


def build_subscribers(
    profile: CompositionProfile,
    progress_state: "ProgressState",
    *,
    env: Mapping[str, str],
) -> Callable[[Any], Any] | None:
    """Attach progress-state subscribers per profile; return comment factory.

    Each name in ``profile.progress_subscribers`` maps to either:

    - A progress-state subscriber (attached immediately via
      ``progress_state.subscribe``): ``dispatcher_event``, ``console``.
    - A comment-driving subscriber that needs a live ``CommentManager``
      to construct (returned as a factory for ``RunContext.make_comment_subscriber``):
      ``gh_comment``.

    Returns the comment-factory callable or ``None`` if the profile
    has no comment-driving subscriber.
    """
    comment_factory: Callable[[Any], Any] | None = None
    for name in profile.progress_subscribers:
        if name == "gh_comment":
            from a2sdlc.adapters.subscriber.gh_comment import (  # noqa: PLC0415
                GhCommentSubscriber,
            )

            def _make(comment: Any, ps: ProgressState = progress_state) -> Any:
                return GhCommentSubscriber(comment, ps)

            comment_factory = _make
        elif name == "console":
            from a2sdlc.adapters.subscriber.console import (  # noqa: PLC0415
                ConsoleSubscriber,
            )

            progress_state.subscribe(ConsoleSubscriber(progress_state))
        elif name == "dispatcher_event":
            import httpx  # noqa: PLC0415

            from a2sdlc.adapters.subscriber.dispatcher_event import (  # noqa: PLC0415
                DispatcherEventSubscriber,
            )

            dispatcher_url = env["DISPATCHER_URL"]
            run_id = env["RUN_ID"]
            run_hmac = env["RUN_HMAC"]
            progress_state.subscribe(
                DispatcherEventSubscriber(
                    dispatcher_url=dispatcher_url,
                    run_id=run_id,
                    run_hmac=run_hmac,
                    http=httpx.Client(timeout=30.0),
                )
            )
        else:
            msg = f"unknown progress subscriber: {name}"
            raise ValueError(msg)
    return comment_factory


__all__ = [
    "CompositionProfile",
    "build_adapters",
    "build_subscribers",
    "resolve_composition_profile",
    "validate_profile",
]
