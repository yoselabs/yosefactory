"""Tests for a2sdlc configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2sdlc.config import (
    PipelineFlags,
    ProjectConfig,
    load_config_file,
    resolve_flags,
    load_stage_config,
)
from a2sdlc.stages import STAGES, get_stage


# ── Stage registry ───────────────────────────────────────────────────


@pytest.mark.unit
class TestStageRegistry:
    def test_stages_registered(self) -> None:
        expected = {"spec", "implement", "review", "merge"}
        assert set(STAGES.keys()) == expected

    def test_spec_config(self) -> None:
        stage = get_stage("spec")
        assert stage.config.model == "claude-sonnet-4-6"
        assert stage.config.max_turns == 150
        assert stage.config.timeout_minutes == 30
        assert "Bash" in stage.config.allowed_tools
        assert "Agent" in stage.config.allowed_tools

    def test_implement_config(self) -> None:
        stage = get_stage("implement")
        assert stage.config.max_turns == 150
        assert stage.config.timeout_minutes == 60

    def test_review_restricted_tools(self) -> None:
        stage = get_stage("review")
        assert "Write" not in stage.config.allowed_tools
        assert "Edit" not in stage.config.allowed_tools

    def test_merge_no_ai(self) -> None:
        stage = get_stage("merge")
        assert stage.uses_ai is False

    def test_unknown_stage_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown stage"):
            get_stage("nonexistent")


# ── PipelineFlags ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestPipelineFlags:
    def test_defaults(self) -> None:
        flags = PipelineFlags()
        assert flags.auto_spec is False
        assert flags.auto_proceed is True
        assert flags.auto_merge is False

    def test_frozen(self) -> None:
        flags = PipelineFlags()
        with pytest.raises(AttributeError):
            flags.auto_spec = True  # type: ignore[misc]  # ty: ignore[invalid-assignment]


# ── resolve_flags ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestResolveFlags:
    def test_no_overrides(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "bug"])
        assert flags == PipelineFlags()

    def test_auto_spec_label(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "auto-spec"])
        assert flags.auto_spec is True
        assert flags.auto_proceed is True

    def test_auto_merge_label(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "auto-merge"])
        assert flags.auto_merge is True

    def test_spec_only_label(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "spec-only"])
        assert flags.auto_proceed is False

    def test_combined_labels(self) -> None:
        flags = resolve_flags(
            PipelineFlags(), labels=["agent", "auto-spec", "auto-merge"]
        )
        assert flags.auto_spec is True
        assert flags.auto_merge is True
        assert flags.auto_proceed is True


# ── load_config_file ──────────────────────────────────────────────────


@pytest.mark.unit
class TestLoadConfigFile:
    def test_load_minimal(self, tmp_path: Path) -> None:
        config_file = tmp_path / "a2sdlc.yaml"
        config_file.write_text("adapter: github\n")
        config = load_config_file(tmp_path)
        assert config.adapter == "github"
        assert config.auto_merge is False
        assert config.default_base == "main"

    def test_load_full(self, tmp_path: Path) -> None:
        config_file = tmp_path / "a2sdlc.yaml"
        config_file.write_text(
            "adapter: github\n"
            "pipeline:\n"
            "  auto_merge: true\n"
            "  default_base: develop\n"
            "stages:\n"
            "  implement:\n"
            "    code_reviews: 3\n"
            "    max_turns: 200\n"
        )
        config = load_config_file(tmp_path)
        assert config.auto_merge is True
        assert config.default_base == "develop"

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_config_file(tmp_path)
        assert config.adapter == "github"

    def test_pipeline_flags_method(self) -> None:
        config = ProjectConfig(auto_spec=True, auto_merge=True)
        flags = config.pipeline_flags()
        assert flags.auto_spec is True
        assert flags.auto_merge is True
        assert flags.auto_proceed is True


# ── load_stage_config ─────────────────────────────────────────────────


@pytest.mark.unit
class TestLoadStageConfig:
    def test_default_stage_config(self) -> None:
        project = ProjectConfig()
        config = load_stage_config("spec", project)
        assert config.name == "spec"
        assert config.max_turns == 150  # spec default

    def test_override_from_project(self) -> None:
        project = ProjectConfig(
            stage_overrides={"implement": {"code_reviews": 3, "max_turns": 200}}
        )
        config = load_stage_config("implement", project)
        assert config.code_reviews == 3
        assert config.max_turns == 200
        assert config.timeout_minutes == 60  # not overridden

    def test_no_override(self) -> None:
        project = ProjectConfig(stage_overrides={"implement": {"code_reviews": 5}})
        config = load_stage_config("spec", project)
        assert config.code_reviews == 0  # spec default, not overridden


# ── get_session_id ───────────────────────────────────────────────────


@pytest.mark.unit
class TestGetSessionId:
    def test_deterministic(self) -> None:
        from a2sdlc.config import get_session_id

        sid1 = get_session_id("PROJ-42", "spec")
        sid2 = get_session_id("PROJ-42", "spec")
        assert sid1 == sid2

    def test_different_keys(self) -> None:
        from a2sdlc.config import get_session_id

        sid1 = get_session_id("PROJ-1", "spec")
        sid2 = get_session_id("PROJ-2", "spec")
        assert sid1 != sid2

    def test_different_agents(self) -> None:
        from a2sdlc.config import get_session_id

        sid1 = get_session_id("PROJ-1", "spec")
        sid2 = get_session_id("PROJ-1", "implement")
        assert sid1 != sid2
