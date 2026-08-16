"""Thresholds are tuning. They still refuse two things: a wall clock CI would beat, and any secret."""

from __future__ import annotations

from pathlib import Path

import pytest

from yosefactory.runtime.config import DEFAULTS, ConfigError, Guardrails, from_mapping, load


def test_defaults_load_when_nothing_is_configured(tmp_path: Path) -> None:
    assert load(tmp_path / "absent.toml") == Guardrails(**DEFAULTS)


def test_the_wall_clock_must_sit_under_the_six_hour_ci_ceiling() -> None:
    with pytest.raises(ConfigError, match="six-hour"):
        from_mapping({"wall_clock_seconds": 6 * 60 * 60})


def test_the_shipped_default_wall_clock_is_well_under_it() -> None:
    assert DEFAULTS["wall_clock_seconds"] < 6 * 60 * 60 / 2


@pytest.mark.parametrize("key", ["token", "api_key", "secret", "home_path"])
def test_no_config_surface_accepts_a_secret_or_a_path(key: str) -> None:
    with pytest.raises(ConfigError):
        from_mapping({key: 1})


def test_an_unknown_setting_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ConfigError, match="unknown guardrail setting"):
        from_mapping({"windwo": 5})


@pytest.mark.parametrize("value", [0, -1, "10", True])
def test_thresholds_must_be_positive_integers(value: object) -> None:
    with pytest.raises(ConfigError, match="window"):
        from_mapping({"window": value})


def test_the_repo_pyproject_is_readable_and_valid() -> None:
    guard = load(Path(__file__).resolve().parents[2] / "pyproject.toml")
    assert guard.window >= 1


def test_no_cost_ceiling_is_the_default() -> None:
    """None means no flag is sent, never a limit substituted on the caller's behalf."""
    assert Guardrails(**DEFAULTS).cost_ceiling_usd is None


def test_a_cost_ceiling_is_accepted_and_readable() -> None:
    guard = from_mapping({"cost_ceiling_usd": 0.02})
    assert guard.cost_ceiling_usd == 0.02


@pytest.mark.parametrize("value", [0, -0.01, True, float("inf"), float("nan")])
def test_a_cost_ceiling_must_be_a_positive_finite_number(value: object) -> None:
    with pytest.raises(ConfigError, match="cost_ceiling_usd"):
        from_mapping({"cost_ceiling_usd": value})
