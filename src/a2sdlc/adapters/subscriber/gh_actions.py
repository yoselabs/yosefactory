"""GhActionsLogSubscriber — workflow-log output via ::group:: markers."""

from __future__ import annotations

import sys

from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    ProgressEvent,
    StageEnd,
    StageStart,
    ToolEntry,
)


class GhActionsLogSubscriber:
    """Prints events to stdout with ::group::/::endgroup:: markers.

    Reproduces the workflow-log output previously emitted by inline prints
    in ``runner.py``. Registered as a subscriber on ``ProgressState``.
    """

    async def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            print(  # noqa: T201
                f"::group::Stage {event.stage.value} (session {event.session_id})",
                file=sys.stdout,
            )
        elif isinstance(event, StageEnd):
            status = "OK" if event.success else "FAIL"
            print(f"Stage {event.stage.value} end: {status}", file=sys.stdout)  # noqa: T201
            print("::endgroup::", file=sys.stdout)  # noqa: T201
        elif isinstance(event, GroupOpen):
            print(f"::group::{event.title}", file=sys.stdout)  # noqa: T201
        elif isinstance(event, GroupClose):
            print("::endgroup::", file=sys.stdout)  # noqa: T201
        elif isinstance(event, ToolEntry):
            # Reproduce the per-tool grouped block from the old runner inline.
            print(f"::group::Tool: {event.name}", file=sys.stdout)  # noqa: T201
            print(f"  target: {event.target}", file=sys.stdout)  # noqa: T201
            print("::endgroup::", file=sys.stdout)  # noqa: T201
