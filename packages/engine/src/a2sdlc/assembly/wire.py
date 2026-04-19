"""Wire runtime objects for CLI entry points.

Both ``cli/dispatch.py`` and ``cli/run_stage.py`` need to build a
``ProgressState`` with subscribers selected by config. This helper
centralises that logic so the CLI modules stay small and consistent.
"""

from __future__ import annotations

from pathlib import Path

from a2sdlc.domain.progress import ProgressState


def build_progress_state(
    project_root: Path,
    progress_adapter_name: str,
    *,
    with_mlflow_trace: bool = False,
) -> ProgressState:
    """Build a ``ProgressState`` and attach subscribers by config name.

    Known ``progress_adapter_name`` values:
      - ``"gh_actions"`` → ``GhActionsLogSubscriber`` (workflow log output).
      - ``"console"``    → ``ConsoleSubscriber`` (rich live pane).
      - anything else    → no user-facing subscriber.

    ``with_mlflow_trace=True`` adds the ``MlflowTraceSubscriber`` last, so
    its failures cannot shadow the primary subscriber.
    """
    state = ProgressState(project_root=str(project_root))

    if progress_adapter_name == "gh_actions":
        from a2sdlc.adapters.subscriber.gh_actions import (  # noqa: PLC0415
            GhActionsLogSubscriber,
        )

        state.subscribe(GhActionsLogSubscriber())
    elif progress_adapter_name == "console":  # pragma: no cover
        from a2sdlc.adapters.subscriber.console import (  # noqa: PLC0415
            ConsoleSubscriber,
        )

        state.subscribe(ConsoleSubscriber(state))

    if with_mlflow_trace:
        from a2sdlc.adapters.subscriber.mlflow_trace import (  # noqa: PLC0415
            MlflowTraceSubscriber,
        )

        state.subscribe(MlflowTraceSubscriber())

    return state
