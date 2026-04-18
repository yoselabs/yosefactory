"""Tests for a2sdlc configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2sdlc.config import (
    ProjectConfig,
    load_config_file,
    load_stage_config,
)
from a2sdlc.domain.models import GateMode
from a2sdlc.stages import STAGES, get_stage


def _write_config(tmp_path: Path, text: str) -> Path:
    """Write ``text`` to ``tmp_path/.a2sdlc/config.yaml`` and return the path."""
    a2sdlc_dir = tmp_path / ".a2sdlc"
    a2sdlc_dir.mkdir(exist_ok=True)
    config_path = a2sdlc_dir / "config.yaml"
    config_path.write_text(text)
    return config_path


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


# ── load_config_file ──────────────────────────────────────────────────


@pytest.mark.unit
class TestLoadConfigFile:
    def test_load_config_reads_from_a2sdlc_subdir(self, tmp_path: Path) -> None:
        """GIVEN a repo with .a2sdlc/config.yaml
        WHEN load_config_file is called with the repo path
        THEN the config is loaded from that file."""
        _write_config(tmp_path, "model: claude-sonnet-4-6\n")
        cfg = load_config_file(tmp_path)
        assert cfg.model == "claude-sonnet-4-6"

    def test_load_minimal(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "default_base: main\n")
        config = load_config_file(tmp_path)
        assert config.default_base == "main"

    def test_load_full(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            "default_base: develop\n"
            "stages:\n"
            "  implement:\n"
            "    code_reviews: 3\n"
            "    max_turns: 200\n",
        )
        config = load_config_file(tmp_path)
        assert config.default_base == "develop"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """GIVEN a repo without .a2sdlc/config.yaml
        WHEN load_config_file is called
        THEN FileNotFoundError is raised with a clear message."""
        with pytest.raises(FileNotFoundError, match=".a2sdlc/config.yaml"):
            load_config_file(tmp_path)

    def test_self_answer_still_works(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "spec:\n  self_answer: true\n")
        config = load_config_file(tmp_path)
        assert config.self_answer is True


# ── ConfigError / strict validation ──────────────────────────────────


@pytest.mark.unit
class TestStrictKeyValidation:
    def test_load_config_rejects_unknown_top_level_keys(self, tmp_path: Path) -> None:
        """GIVEN a config with a typo'd top-level key
        WHEN loaded
        THEN raises ConfigError listing the unknown key."""
        _write_config(tmp_path, "modell: x\n")  # typo

        from a2sdlc.config import ConfigError

        with pytest.raises(ConfigError, match="modell"):
            load_config_file(tmp_path)

    def test_all_allowed_keys_accepted(self, tmp_path: Path) -> None:
        """GIVEN a config containing every allowed top-level key
        WHEN loaded
        THEN no ConfigError is raised."""
        _write_config(
            tmp_path,
            "adapters: {}\n"
            "stages: {}\n"
            "spec: {}\n"
            "quality: {}\n"
            "model: claude-sonnet-4-6\n"
            "default_base: main\n"
            "max_turns_per_stage: 50\n"
            "gates: {}\n"
            "self_answer: true\n"
            "resume: false\n"
            "timeouts: {}\n",
        )
        # Should not raise.
        config = load_config_file(tmp_path)
        assert config.model == "claude-sonnet-4-6"


# ── AdaptersConfig / QualityConfig ───────────────────────────────────


@pytest.mark.unit
class TestAdaptersAndQualityBlocks:
    def test_load_config_parses_adapters_block(self, tmp_path: Path) -> None:
        """GIVEN a config with adapters: {work, review, git, progress}
        WHEN loaded
        THEN Config.adapters holds those four names."""
        _write_config(
            tmp_path,
            "adapters:\n  work: local_file\n  review: local_noop\n"
            "  git: local_branch\n  progress: console\n",
        )
        cfg = load_config_file(tmp_path)
        assert cfg.adapters.work == "local_file"
        assert cfg.adapters.review == "local_noop"
        assert cfg.adapters.git == "local_branch"
        assert cfg.adapters.progress == "console"

    def test_adapters_defaults_when_missing(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "model: claude-sonnet-4-6\n")
        cfg = load_config_file(tmp_path)
        assert cfg.adapters.work == "jira"
        assert cfg.adapters.review == "github"
        assert cfg.adapters.git == "github"
        assert cfg.adapters.progress == "gh_actions"

    def test_quality_parses_check_command(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "quality:\n  check_command: make ci\n")
        cfg = load_config_file(tmp_path)
        assert cfg.quality.check_command == "make ci"

    def test_quality_default(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "model: claude-sonnet-4-6\n")
        cfg = load_config_file(tmp_path)
        assert cfg.quality.check_command == "make check"


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

    def test_different_review_cycles_produce_different_ids(self) -> None:
        from a2sdlc.config import get_session_id

        sid0 = get_session_id("PROJ-1", "review", review_cycles=0)
        sid1 = get_session_id("PROJ-1", "review", review_cycles=1)
        sid2 = get_session_id("PROJ-1", "review", review_cycles=2)
        assert sid0 != sid1
        assert sid1 != sid2
        assert sid0 != sid2

    def test_deterministic_with_review_cycles(self) -> None:
        from a2sdlc.config import get_session_id

        sid1 = get_session_id("PROJ-42", "review", review_cycles=3)
        sid2 = get_session_id("PROJ-42", "review", review_cycles=3)
        assert sid1 == sid2

    def test_default_review_cycles_backward_compat(self) -> None:
        from a2sdlc.config import get_session_id

        # Calling with explicit 0 should match default
        sid_default = get_session_id("PROJ-1", "spec")
        sid_explicit = get_session_id("PROJ-1", "spec", review_cycles=0)
        assert sid_default == sid_explicit


# ── gate_config ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestGateConfig:
    def test_defaults_merge_human_spec_auto(self) -> None:
        config = ProjectConfig()
        gates = config.gate_config()
        assert gates.merge == GateMode.HUMAN
        assert gates.spec == GateMode.AUTO

    def test_parse_merge_auto_from_yaml(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "gates:\n  merge: auto\n")
        config = load_config_file(tmp_path)
        gates = config.gate_config()
        assert gates.merge == GateMode.AUTO
        assert gates.spec == GateMode.AUTO  # default

    def test_parse_both_gates_from_yaml(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "gates:\n  merge: auto\n  spec: human\n")
        config = load_config_file(tmp_path)
        gates = config.gate_config()
        assert gates.merge == GateMode.AUTO
        assert gates.spec == GateMode.HUMAN

    def test_no_gates_section_uses_defaults(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "model: claude-sonnet-4-6\n")
        config = load_config_file(tmp_path)
        gates = config.gate_config()
        assert gates.merge == GateMode.HUMAN
        assert gates.spec == GateMode.AUTO

    def test_default_base_without_gates_uses_defaults(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "default_base: develop\n")
        config = load_config_file(tmp_path)
        gates = config.gate_config()
        assert gates.merge == GateMode.HUMAN
        assert gates.spec == GateMode.AUTO

    def test_self_answer_independent_of_gates(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            "spec:\n  self_answer: true\ngates:\n  merge: auto\n",
        )
        config = load_config_file(tmp_path)
        assert config.self_answer is True
        assert config.gate_config().merge == GateMode.AUTO

    def test_self_answer_loaded_from_yaml(self, tmp_path: Path) -> None:
        """YAML path spec.self_answer sets self_answer=True."""
        _write_config(tmp_path, "spec:\n  self_answer: true\n")
        config = load_config_file(tmp_path)
        assert config.self_answer is True
