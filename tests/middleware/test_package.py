"""L1 smoke test — the middleware package + type aliases import cleanly."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_aliases_importable() -> None:
    from a2sdlc.middleware import Middleware, StageAttempt

    # Alias identities aren't load-bearing; this test pins that both
    # names resolve + survive refactors that rename the module path.
    assert StageAttempt is not None
    assert Middleware is not None
