"""L1 tests for ``assembly.composition.CompositionProfile``.

P6 step 1 — shape-only. Resolver, validator, and builders land in
later steps with their own tests.
"""

from __future__ import annotations

import pytest

from a2sdlc.assembly.composition import CompositionProfile


@pytest.mark.unit
class TestCompositionProfile:
    def test_local_file_profile_constructs(self) -> None:
        profile = CompositionProfile(
            work="local_file",
            review="local_noop",
            git="local_branch",
            progress_subscribers=("gh_comment",),
            credential_profile="github_token",
        )
        assert profile.work == "local_file"
        assert profile.review == "local_noop"
        assert profile.git == "local_branch"
        assert profile.progress_subscribers == ("gh_comment",)
        assert profile.credential_profile == "github_token"

    def test_ci_github_native_profile_constructs(self) -> None:
        profile = CompositionProfile(
            work="github_issue",
            review="github",
            git="local",
            progress_subscribers=("gh_comment",),
            credential_profile="github_token",
        )
        assert profile.work == "github_issue"
        assert profile.progress_subscribers == ("gh_comment",)

    def test_ci_dispatcher_profile_constructs(self) -> None:
        profile = CompositionProfile(
            work="workflow_input",
            review="github",
            git="local",
            progress_subscribers=("dispatcher_event", "console"),
            credential_profile="github_token",
        )
        assert profile.work == "workflow_input"
        assert "dispatcher_event" in profile.progress_subscribers
        assert "console" in profile.progress_subscribers

    def test_profile_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError  # noqa: PLC0415

        profile = CompositionProfile(
            work="local_file",
            review="local_noop",
            git="local_branch",
            progress_subscribers=(),
            credential_profile="github_token",
        )
        field = "work"
        with pytest.raises(FrozenInstanceError):
            setattr(profile, field, "github_issue")
