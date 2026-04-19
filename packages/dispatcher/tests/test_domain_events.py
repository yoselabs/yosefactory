import pytest
from pydantic import ValidationError
from a2sdlc_dispatcher.domain_events import DomainEventAdapter


def test_parse_run_started():
    data = {"kind": "run_started", "run_id": "abc", "mlflow_url": "https://m/r/1"}
    evt = DomainEventAdapter.validate_python(data)
    assert evt.kind == "run_started"
    assert evt.run_id == "abc"
    assert evt.mlflow_url == "https://m/r/1"


def test_parse_stage_started():
    evt = DomainEventAdapter.validate_python(
        {"kind": "stage_started", "stage": "implement"}
    )
    assert evt.kind == "stage_started"
    assert evt.stage == "implement"


def test_parse_pr_opened():
    evt = DomainEventAdapter.validate_python(
        {
            "kind": "pr_opened",
            "url": "https://github.com/x/y/pull/1",
            "base": "main",
            "head": "x/y",
        }
    )
    assert evt.kind == "pr_opened"
    assert evt.base == "main"


def test_parse_run_failed():
    evt = DomainEventAdapter.validate_python({"kind": "run_failed", "error": "boom"})
    assert evt.kind == "run_failed"
    assert evt.error == "boom"


def test_parse_unknown_kind_is_accepted_as_raw():
    evt = DomainEventAdapter.validate_python({"kind": "future_event_v2", "foo": "bar"})
    # Unknown kind is accepted silently via the discriminated-union fallback,
    # for forward compatibility (engine may emit new kinds ahead of dispatcher).
    assert evt.kind == "future_event_v2"


def test_parse_missing_kind_raises():
    with pytest.raises(ValidationError):
        DomainEventAdapter.validate_python({"run_id": "abc"})
