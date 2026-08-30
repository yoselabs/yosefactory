"""`SURFACE`/`_ADAPTER_METHODS` name every signature a foreign runner may depend on directly
(module docstring). This is the demonstration that a signature change is caught: it fails when a
declared entry's live signature moves out from under it, the same way `PINNED_VERSION` drift fails
loudly in `tests/runtime/test_turn_integration.py::test_the_wrapper_matches_the_executor_protocol`.
"""

from __future__ import annotations

import inspect

import pytest

from yosefactory.protocol import integration_surface
from yosefactory.protocol.integration_surface import (
    _ADAPTER_METHODS,
    SURFACE,
    Entry,
    SurfaceDrift,
    assert_fits,
    check,
)


def test_the_declared_surface_matches_the_live_one() -> None:
    assert check() == ()


def test_assert_fits_is_silent_when_the_surface_matches() -> None:
    assert_fits()  # must not raise


def test_every_declared_signature_is_live_inspect_signature_verbatim() -> None:
    """Guards the fixture itself: a hand-typed `signature` string that quietly drifted from what
    `inspect.signature` actually renders for that target would make `check()` pass for the wrong
    reason -- comparing against a stale string rather than the target's real shape."""
    for entry in (*SURFACE, *_ADAPTER_METHODS):
        assert entry.signature == str(inspect.signature(entry.target)), entry.qualname


def test_a_drifted_signature_is_reported_by_qualname() -> None:
    drifted = Entry(qualname="fake.thing", target=lambda a, b: None, signature="(a) -> None")
    original = integration_surface.SURFACE
    try:
        integration_surface.SURFACE = (drifted,)
        mismatches = check()
        assert len(mismatches) == 1
        assert mismatches[0].qualname == "fake.thing"
        assert mismatches[0].declared == "(a) -> None"
        assert mismatches[0].live == "(a, b)"
        with pytest.raises(SurfaceDrift, match=r"fake\.thing"):
            assert_fits()
    finally:
        integration_surface.SURFACE = original
