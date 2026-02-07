"""Tests for a2sdlc.config — StageConfig, ProjectConfig, load functions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from a2sdlc.config import (
    STAGE_DEFAULTS,
    ProjectConfig,
    StageConfig,
    get_session_id,
    load_config,
    load_project,
)


# ── StageConfig defaults ──────────────────────────────────────────────


@pytest.mark.unit
class TestStageDefaults:
    def test_stage_defaults_exist(self) -> None:
        expected = {"spec", "implement", "review"}
        assert set(STAGE_DEFAULTS.keys()) == expected
        for cfg in STAGE_DEFAULTS.values():
            assert isinstance(cfg, StageConfig)

    def test_spec_defaults(self) -> None:
        cfg = STAGE_DEFAULTS["spec"]
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.max_turns == 35
        assert cfg.timeout_minutes == 30
        assert "Bash" in cfg.allowed_tools
        assert "Agent" in cfg.allowed_tools

    def test_implement_defaults(self) -> None:
        cfg = STAGE_DEFAULTS["implement"]
        assert cfg.max_turns == 120
        assert cfg.timeout_minutes == 60


# ── load_config overrides ─────────────────────────────────────────────


@pytest.mark.unit
class TestLoadConfig:
    def test_override_model(self) -> None:
        cfg = load_config("spec", model="claude-opus-4")
        assert cfg.model == "claude-opus-4"
        assert cfg.max_turns == 35

    def test_override_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODEL", "claude-haiku-4")
        monkeypatch.setenv("MAX_TURNS", "99")
        cfg = load_config("spec")
        assert cfg.model == "claude-haiku-4"
        assert cfg.max_turns == 99

    def test_cli_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODEL", "from-env")
        cfg = load_config("spec", model="from-cli")
        assert cfg.model == "from-cli"


# ── get_session_id ───────────────────────────────────────────────────


@pytest.mark.unit
class TestGetSessionId:
    def test_deterministic(self) -> None:
        sid1 = get_session_id("PROJ-42", "spec")
        sid2 = get_session_id("PROJ-42", "spec")
        assert sid1 == sid2

    def test_different_keys(self) -> None:
        sid1 = get_session_id("PROJ-1", "spec")
        sid2 = get_session_id("PROJ-2", "spec")
        assert sid1 != sid2

    def test_different_agents(self) -> None:
        sid1 = get_session_id("PROJ-1", "spec")
        sid2 = get_session_id("PROJ-1", "implement")
        assert sid1 != sid2


# ── ProjectConfig ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestProjectConfig:
    def test_load_project_missing(self, tmp_path: Path) -> None:
        cfg = load_project(tmp_path)
        assert cfg == ProjectConfig()
        assert cfg.tickets_adapter == "github-issues"
        assert cfg.test_command == "make test"

    def test_load_project_with_file(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".a2sdlc"
        config_dir.mkdir()
        config_file = config_dir / "project.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "adapters": {"tickets": "jira", "code": "gitlab"},
                    "testing": {"command": "pytest -x"},
                    "jira_status_map": {"todo": "To Do", "done": "Done"},
                }
            )
        )
        cfg = load_project(tmp_path)
        assert cfg.tickets_adapter == "jira"
        assert cfg.code_adapter == "gitlab"
        assert cfg.test_command == "pytest -x"
        assert cfg.jira_status_map == {"todo": "To Do", "done": "Done"}
