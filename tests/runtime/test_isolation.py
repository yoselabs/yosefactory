"""Policy only: default isolated, no bare mode, a preflight that leaks no path and spawns nothing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yosefactory.runtime.isolation import IsolationError, IsolationPolicy, Reason, preflight, resolve


def _reachable(root: Path) -> Path:
    """A home the credential store can be found from, on whichever platform the tests run."""
    (root / "Library" / "Keychains").mkdir(parents=True, exist_ok=True)
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / ".credentials.json").write_text("{}", encoding="utf-8")
    return root


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


def test_an_isolated_policy_may_not_ask_for_a_tool_server_it_would_not_get() -> None:
    """Safe mode ignores an explicit --mcp-config. Emitting one anyway is a silent nothing."""
    with pytest.raises(IsolationError, match="silently would not be there"):
        IsolationPolicy(isolated=True, mcp_config_path="/somewhere/servers.json")

    opted_out = IsolationPolicy(isolated=False, opt_out_reason="stated", mcp_config_path="/somewhere/servers.json")
    assert opted_out.mcp_config_path


def test_a_home_the_credential_is_reachable_from_passes(tmp_path: Path) -> None:
    result = preflight(_reachable(tmp_path), interactive=False)
    assert result.ok
    assert result.reasons == (Reason.CLEAN,)


def test_an_emptied_home_is_caught_before_the_run(tmp_path: Path) -> None:
    """The inversion, and it is the point of this preflight.

    The old check asserted this home was *empty* and passed it. Measured, such a run does not isolate
    — it stops: the subscription credential lives in the host keychain under `$HOME`, so a fresh home
    cannot look it up and the run reports `Not logged in` having done nothing. An emptied home also
    leaves repository configuration entirely untouched, so it never bought what it was credited with.
    """
    result = preflight(tmp_path, interactive=False)

    assert not result.ok
    assert Reason.CREDENTIAL_UNREACHABLE in result.reasons


def test_an_unset_home_is_a_failure_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOME", raising=False)

    result = preflight(interactive=False)

    assert not result.ok
    assert Reason.HOME_UNSET in result.reasons


def test_a_session_that_could_be_suspended_by_a_prompt_is_refused(tmp_path: Path) -> None:
    result = preflight(_reachable(tmp_path), interactive=True)

    assert not result.ok
    assert Reason.PROMPT_CAN_SUSPEND in result.reasons


def test_the_preflight_leaks_no_path_in_either_result(tmp_path: Path) -> None:
    failed = preflight(tmp_path, interactive=True).report()
    passed = preflight(_reachable(tmp_path), interactive=False).report()

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
    preflight(_reachable(tmp_path), interactive=False)
