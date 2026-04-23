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


__all__ = ["CompositionProfile"]
