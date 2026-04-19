"""Translate engine-emitted domain events into Jira comments + transitions.

Key semantics:

- Engine invocations in CI are one-stage-per-run-per-process. To avoid spamming
  Jira with re-transitions, the dispatcher itself dedupes "Ready → In Progress"
  using a flag in RunsTable — fired on the FIRST stage_started received for
  a given run_id. Subsequent stage_started events become comments only.
- The final `stage_completed(stage="merge", ok=True)` means the PR has been
  opened and is awaiting human merge — transition to In Review.
- Any `stage_completed(ok=False)` transitions to Blocked with the summary.
"""

from __future__ import annotations

from a2sdlc_dispatcher.domain_events import (
    PROpened,
    PRUpdated,
    RunCompleted,
    RunFailed,
    StageCompleted,
    StageStarted,
    UnknownEvent,
)
from a2sdlc_dispatcher.jira_client import JiraClient
from a2sdlc_dispatcher.runs_table import RunsTable
from a2sdlc_dispatcher.settings import ProjectConfig


def translate_event_to_jira(
    jira: JiraClient,
    *,
    project: ProjectConfig,
    ticket_key: str,
    run_id: str,
    runs: RunsTable,
    event,
) -> None:
    """Dispatch on event type.

    Unknown event kinds are silently ignored (forward compat).
    """
    if isinstance(event, StageStarted):
        if not runs.has_in_progress_been_sent(run_id):
            jira.transition(ticket_key, to_status=project.status_in_progress)
            runs.mark_in_progress_sent(run_id)
            jira.add_comment(
                ticket_key, f":rocket: Run started — entering stage: **{event.stage}**"
            )
        else:
            jira.add_comment(ticket_key, f"▶ Entering stage: **{event.stage}**")

    elif isinstance(event, StageCompleted):
        if not event.ok:
            jira.transition(ticket_key, to_status=project.status_blocked)
            summary = event.summary or "(no summary)"
            jira.add_comment(ticket_key, f":x: Stage `{event.stage}` failed: {summary}")
            return
        if event.stage == "merge":
            jira.transition(ticket_key, to_status=project.status_review)
            body = ":white_check_mark: Merge stage complete — PR awaiting human review/merge"
            if event.summary:
                body += f"\n{event.summary}"
            jira.add_comment(ticket_key, body)

    elif isinstance(event, PROpened):
        jira.add_comment(
            ticket_key,
            f":open_file_folder: PR opened: {event.url} ({event.head} → {event.base})",
        )

    elif isinstance(event, PRUpdated):
        jira.add_comment(
            ticket_key, f":arrows_counterclockwise: PR {event.update_kind}: {event.url}"
        )
        if event.update_kind == "approved":
            jira.transition(ticket_key, to_status=project.status_review)

    elif isinstance(event, RunCompleted):
        # Kept for forward-compat; current engine drives review transition via
        # StageCompleted(stage="merge", ok=True) instead.
        if event.outcome == "awaiting_merge":
            jira.transition(ticket_key, to_status=project.status_review)

    elif isinstance(event, RunFailed):
        jira.transition(ticket_key, to_status=project.status_blocked)
        body = f":x: Run failed: {event.error}"
        if event.mlflow_url:
            body += f"\nMLflow: {event.mlflow_url}"
        jira.add_comment(ticket_key, body)

    elif isinstance(event, UnknownEvent):
        # Forward-compat: engine may emit kinds the dispatcher doesn't understand yet.
        return
