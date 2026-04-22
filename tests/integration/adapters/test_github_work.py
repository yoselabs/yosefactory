"""Recorded integration tests for GitHubWorkAdapter.

Replay-only in CI (`make test-integration`). Re-record with
`make record-integration` against `iorlas/a2sdlc-smoke` using a live
installation token — see docs/mode2/README.md.

Covers the auth-sensitive paths where unit-test mocks would miss a
PyGithub auth-mode mismatch: `from_token` → `get_repo`, then reads that
all share the installation-token code path (`/repos/:owner/:repo/*`).

Read-only by design: tests against a fixed, stable issue and its PR.
Write paths (labels, comments, close) would mutate the smoke repo on
every re-record, which isn't worth the fidelity gain for auth coverage.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from a2sdlc.adapters.work.github import GitHubWorkAdapter


# Stable entity in iorlas/a2sdlc-smoke. Must be a closed, merged ticket
# so the recorded responses don't drift between re-records. Pick any
# completed smoke ticket; #12 is documented as merged in the 2026-04-21
# handover. Override by setting A2SDLC_SMOKE_TICKET if recording against
# a different fixture issue.
KNOWN_TICKET = "12"


pytestmark = [pytest.mark.integration, pytest.mark.vcr]


def test_from_token_constructs_adapter(gh_token: str, smoke_repo: str) -> None:
    """Round-trip: construct via factory, confirm repo access works.

    Catches both auth bugs from 2026-04-21:
    - `ghs_` prefix sniff (false rejection) — factory rejects before HTTP.
    - `get_app()` probe (AssertionError) — factory silently blows up pre-
      return. Cassette replay surfaces either immediately.
    """
    adapter = GitHubWorkAdapter.from_token(gh_token, smoke_repo)
    assert adapter is not None


def test_get_ticket_returns_body(gh_token: str, smoke_repo: str) -> None:
    adapter = GitHubWorkAdapter.from_token(gh_token, smoke_repo)
    body = adapter.get_ticket(KNOWN_TICKET)
    assert isinstance(body, str)


def test_get_ticket_title_nonempty(gh_token: str, smoke_repo: str) -> None:
    adapter = GitHubWorkAdapter.from_token(gh_token, smoke_repo)
    title = adapter.get_ticket_title(KNOWN_TICKET)
    assert isinstance(title, str)
    assert title, "expected a non-empty title on the recorded ticket"


def test_is_ticket_active_false_on_closed(gh_token: str, smoke_repo: str) -> None:
    """The known-merged ticket must report inactive — guards the is_closed
    short-circuit in dispatch.
    """
    adapter = GitHubWorkAdapter.from_token(gh_token, smoke_repo)
    assert adapter.is_ticket_active(KNOWN_TICKET) is False


def test_get_labels_returns_list(gh_token: str, smoke_repo: str) -> None:
    adapter = GitHubWorkAdapter.from_token(gh_token, smoke_repo)
    labels = adapter.get_labels(KNOWN_TICKET)
    assert isinstance(labels, list)
    assert all(isinstance(name, str) for name in labels)


def test_get_current_stage_on_closed_ticket(gh_token: str, smoke_repo: str) -> None:
    """Closed tickets have all stage:* labels stripped by mark_done —
    stage should be None. Confirms the label → StageName mapping path
    doesn't crash on an empty label set.
    """
    adapter = GitHubWorkAdapter.from_token(gh_token, smoke_repo)
    stage = adapter.get_current_stage(KNOWN_TICKET)
    assert stage is None


def test_collect_issue_feedback_accepts_since(gh_token: str, smoke_repo: str) -> None:
    """`get_comments(since=...)` is a tz-aware API quirk; exercises the
    datetime pass-through end-to-end. Result shape only — content
    depends on the recorded issue.
    """
    adapter = GitHubWorkAdapter.from_token(gh_token, smoke_repo)
    since = datetime(2020, 1, 1, tzinfo=UTC)
    items = adapter.collect_issue_feedback(KNOWN_TICKET, since)
    assert isinstance(items, list)
