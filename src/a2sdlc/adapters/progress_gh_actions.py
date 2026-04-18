"""GitHub Actions progress adapter — emits ::group:: / ::endgroup:: markers."""

from __future__ import annotations

import sys

from a2sdlc.domain.models import StageName


class GhActionsProgressAdapter:
    """Prints events as plain lines, with ::group:: markers for logical blocks.

    Implements ProgressAdapter (see adapters/protocols.py). Preserves the
    existing CI-side rendering behavior previously embedded in pipeline/runner.py
    and pipeline/dispatch.py — so that when Task 9 wires this adapter in,
    CI output is byte-identical to today.
    """

    def on_stage_start(self, stage: StageName, session_id: str) -> None:
        print(f"::group::Stage {stage.value} (session {session_id})", file=sys.stdout)  # noqa: T201

    def on_event(self, event_type: str, text: str) -> None:
        print(f"[{event_type}] {text}", file=sys.stdout)  # noqa: T201

    def on_stage_end(self, stage: StageName, success: bool) -> None:
        status = "OK" if success else "FAIL"
        print(f"Stage {stage.value} end: {status}", file=sys.stdout)  # noqa: T201
        print("::endgroup::", file=sys.stdout)  # noqa: T201

    def on_group_open(self, title: str) -> None:
        print(f"::group::{title}", file=sys.stdout)  # noqa: T201

    def on_group_close(self) -> None:
        print("::endgroup::", file=sys.stdout)  # noqa: T201
