"""REQUIRED_ENV aggregation + fail-fast validator."""

from __future__ import annotations

from a2sdlc.runtime.env_check import (
    MissingEnvVar,
    check_required_env,
    format_missing_message,
)


def test_no_missing_returns_empty(monkeypatch):
    monkeypatch.setenv("FOO", "1")
    monkeypatch.setenv("BAR", "2")
    missing = check_required_env([("engine", ["FOO"]), ("adapter:work", ["BAR"])])
    assert missing == []


def test_missing_aggregates(monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAR", raising=False)
    missing = check_required_env([("engine", ["FOO"]), ("adapter:work", ["BAR"])])
    assert MissingEnvVar(name="FOO", source="engine") in missing
    assert MissingEnvVar(name="BAR", source="adapter:work") in missing


def test_format_missing_message_shape():
    msg = format_missing_message(
        [
            MissingEnvVar(name="ANTHROPIC_API_KEY", source="engine"),
            MissingEnvVar(name="GITHUB_TOKEN", source="adapter:github-work"),
        ]
    )
    assert "ANTHROPIC_API_KEY" in msg
    assert "(engine)" in msg
    assert "GITHUB_TOKEN" in msg
    assert "(adapter:github-work)" in msg
    assert msg.startswith("error:")
