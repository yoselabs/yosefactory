"""Board-test fixtures, here rather than imported into each module.

`gh` was originally imported from `fake_gh` into every test that wanted it, which made each test's
own `gh` parameter a redefinition of the imported name (ruff F811, seven times). A `conftest.py` is
how pytest is meant to share a fixture: the tests take the parameter and import nothing, so there is
no name to shadow.
"""

from __future__ import annotations

from .fake_gh import gh

__all__ = ["gh"]
