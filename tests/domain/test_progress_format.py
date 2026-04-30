"""Token / duration formatters used by the stats line."""

from __future__ import annotations

import pytest

from a2sdlc.domain.progress_format import _format_tokens_precise


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "0"),
        (1, "1"),
        (999, "999"),
        (1_000, "1.0k"),
        (12_400, "12.4k"),
        (38_237, "38.2k"),
        (999_999, "1000.0k"),
        (1_000_000, "1.0M"),
        (2_500_000, "2.5M"),
    ],
)
def test_format_tokens_precise(n: int, expected: str) -> None:
    assert _format_tokens_precise(n) == expected
