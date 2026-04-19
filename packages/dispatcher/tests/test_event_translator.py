from unittest.mock import MagicMock
from a2sdlc_dispatcher.event_translator import translate_event_to_jira
from a2sdlc_dispatcher.domain_events import (
    PROpened,
    PRUpdated,
    RunFailed,
    StageCompleted,
    StageStarted,
)
from a2sdlc_dispatcher.settings import ProjectConfig


def proj() -> ProjectConfig:
    return ProjectConfig(jira_key="A2X", repo="acme/webapp")


def _runs_with_registered(run_id="r1", ticket="A2X-42"):
    from a2sdlc_dispatcher.runs_table import RunsTable

    t = RunsTable()
    t.register(run_id=run_id, ticket_key=ticket, repo="acme/webapp", project_key="A2X")
    return t


def test_first_stage_started_transitions_in_progress_and_dedupes():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageStarted(stage="spec")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.transition.assert_called_once_with("A2X-42", to_status="In Progress")
    # Idempotent: second stage_started in the same run does NOT re-transition.
    jira.reset_mock()
    evt2 = StageStarted(stage="implement")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt2
    )
    jira.transition.assert_not_called()
    jira.add_comment.assert_called_once()
    assert "implement" in jira.add_comment.call_args[0][1]


def test_stage_completed_ok_non_merge_is_noop():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageCompleted(stage="implement", ok=True)
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.transition.assert_not_called()
    jira.add_comment.assert_not_called()


def test_stage_completed_merge_ok_transitions_in_review():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageCompleted(stage="merge", ok=True, summary="PR #1 opened")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.transition.assert_called_once_with("A2X-42", to_status="In Review")


def test_stage_completed_failure_transitions_to_blocked():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = StageCompleted(stage="implement", ok=False, summary="syntax error")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.transition.assert_called_once_with("A2X-42", to_status="Blocked")
    jira.add_comment.assert_called_once()
    assert "syntax error" in jira.add_comment.call_args[0][1]


def test_pr_opened_comments_pr_url():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = PROpened(url="https://github.com/x/y/pull/1", base="main", head="x/y")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.add_comment.assert_called_once()
    assert "pull/1" in jira.add_comment.call_args[0][1]


def test_pr_updated_approved_transitions_in_review():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = PRUpdated(url="https://github.com/x/y/pull/1", update_kind="approved")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.transition.assert_called_once_with("A2X-42", to_status="In Review")


def test_run_failed_transitions_blocked():
    jira = MagicMock()
    runs = _runs_with_registered()
    evt = RunFailed(error="rate limit")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.transition.assert_called_once_with("A2X-42", to_status="Blocked")
    jira.add_comment.assert_called_once()
    assert "rate limit" in jira.add_comment.call_args[0][1]


def test_unknown_event_is_silent():
    from a2sdlc_dispatcher.domain_events import UnknownEvent

    jira = MagicMock()
    runs = _runs_with_registered()
    evt = UnknownEvent(kind="future_v2")
    translate_event_to_jira(
        jira, project=proj(), ticket_key="A2X-42", run_id="r1", runs=runs, event=evt
    )
    jira.transition.assert_not_called()
    jira.add_comment.assert_not_called()
