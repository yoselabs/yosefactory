"""Policy only: default isolated, no bare mode, a preflight that leaks no path and spawns nothing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yosefactory.runtime.isolation import IsolationError, IsolationPolicy, Reason, preflight, resolve


def test_absent_configuration_means_isolated() -> None:
    assert resolve(None).isolated is True


def test_opting_out_requires_a_stated_reason() -> None:
    with pytest.raises(IsolationError, match="omission is not an opt-out"):
        IsolationPolicy(isolated=False)


def test_an_explicit_opt_out_is_allowed_and_carries_its_reason() -> None:
    policy = resolve(False, opt_out_reason="loop needs the repo's own conventions")
    assert policy.isolated is False
    assert policy.opt_out_reason


def test_bare_mode_is_never_selected_in_either_posture() -> None:
    assert resolve(True).uses_bare_mode is False
    assert resolve(False, opt_out_reason="stated").uses_bare_mode is False


def test_a_clean_home_passes(tmp_path: Path) -> None:
    result = preflight(tmp_path, interactive=False)
    assert result.ok
    assert result.reasons == (Reason.CLEAN,)


def test_user_config_in_home_is_caught_before_the_run(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()

    result = preflight(tmp_path, interactive=False)

    assert not result.ok
    assert Reason.USER_CONFIG_PRESENT in result.reasons


def test_an_unset_home_is_a_failure_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOME", raising=False)

    result = preflight(interactive=False)

    assert not result.ok
    assert Reason.HOME_UNSET in result.reasons


def test_a_session_that_could_be_suspended_by_a_prompt_is_refused(tmp_path: Path) -> None:
    result = preflight(tmp_path, interactive=True)

    assert not result.ok
    assert Reason.PROMPT_CAN_SUSPEND in result.reasons


def test_the_preflight_leaks_no_path_in_either_result(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()

    failed = preflight(tmp_path, interactive=True).report()
    passed = preflight(tmp_path.parent / "empty", interactive=False).report()

    for report in (failed, passed):
        assert str(tmp_path) not in report
        assert "/Users/" not in report
        assert "/home/" not in report


def test_resolving_a_policy_and_running_the_preflight_spawns_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """This capability stops at policy. Turning policy into flags belongs to the executor wrapper."""

    def explode(*args: object, **kwargs: object) -> None:
        pytest.fail("isolation must not spawn a process")

    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "run", explode)

    resolve(None)
    preflight(tmp_path, interactive=False)
