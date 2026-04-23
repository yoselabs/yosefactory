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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


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


__all__ = ["CompositionProfile", "resolve_composition_profile", "validate_profile"]
