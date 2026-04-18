"""Adapter registry."""

from __future__ import annotations

from a2sdlc.adapters.git import GitAdapter
from a2sdlc.adapters.review import Approval, ReviewAdapter, ReviewComment
from a2sdlc.adapters.runner import StageRunner
from a2sdlc.adapters.work import PipelineEvent, WorkAdapter

__all__ = [
    "GitAdapter",
    "StageRunner",
    "PipelineEvent",
    "WorkAdapter",
    "Approval",
    "ReviewComment",
    "ReviewAdapter",
]
