"""L1 tests for ``assembly.composition.CompositionProfile``.

P6 step 1 — shape-only. Resolver, validator, and builders land in
later steps with their own tests.
"""

from __future__ import annotations

import pytest

from a2sdlc.assembly.composition import (
    CompositionProfile,
    resolve_composition_profile,
    validate_profile,
)


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


@pytest.mark.unit
class TestResolveCompositionProfile:
    def test_run_stage_resolves_to_local_file(self) -> None:
        profile = resolve_composition_profile(env={}, mode="run-stage")
        assert profile.work == "local_file"
        assert profile.review == "local_noop"
        assert profile.git == "local_branch"
        assert profile.progress_subscribers == ("gh_comment",)

    def test_dispatch_with_dispatcher_url_resolves_to_ci_dispatcher(self) -> None:
        profile = resolve_composition_profile(
            env={"DISPATCHER_URL": "http://d"},
            mode="dispatch",
        )
        assert profile.work == "workflow_input"
        assert profile.review == "github"
        assert "dispatcher_event" in profile.progress_subscribers
        assert "console" in profile.progress_subscribers

    def test_dispatch_without_dispatcher_url_resolves_to_ci_github_native(
        self,
    ) -> None:
        profile = resolve_composition_profile(env={}, mode="dispatch")
        assert profile.work == "github_issue"
        assert profile.review == "github"
        assert profile.git == "local"
        assert profile.progress_subscribers == ("gh_comment",)


@pytest.mark.unit
class TestValidateProfile:
    def test_valid_profiles_pass(self) -> None:
        for mode in ("dispatch", "run-stage"):
            env = {"DISPATCHER_URL": "http://d"} if mode == "dispatch" else {}
            profile = resolve_composition_profile(env=env, mode=mode)
            validate_profile(profile)  # no raise

    def test_workflow_input_without_dispatcher_event_raises(self) -> None:
        profile = CompositionProfile(
            work="workflow_input",
            review="github",
            git="local",
            progress_subscribers=("gh_comment",),
            credential_profile="github_token",
        )
        with pytest.raises(ValueError, match="dispatcher_event"):
            validate_profile(profile)

    def test_dual_app_credential_profile_raises(self) -> None:
        profile = CompositionProfile(
            work="github_issue",
            review="github",
            git="local",
            progress_subscribers=("gh_comment",),
            credential_profile="dual_app",
        )
        with pytest.raises(NotImplementedError, match="dual_app"):
            validate_profile(profile)
