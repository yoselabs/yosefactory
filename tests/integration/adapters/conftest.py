"""Fixtures for recorded GitHub adapter tests.

The cassette replay catches auth-mode mismatches that unit-test mocks
miss — PyGithub's real constraint is that `/app` endpoints require JWT
`AppAuth` while `/installation/*` and `/repos/*` accept installation
tokens. A mock returns whatever we tell it to, so a call that would
`AssertionError` at runtime passes tests green. See
`Evolution/signals/2026-04-21-2341-unit-tests-miss-gh-token-auth-bugs.yaml`.

Cassettes are recorded once against the smoke repo with a real
installation token (`make record-integration`) and replayed in CI with
no network. The scrubber here removes the live token before cassettes
hit disk — re-recording and CI replay both use the same scrubbed form.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


SMOKE_REPO = "iorlas/a2sdlc-smoke"
FAKE_TOKEN = "ghs_faketoken000000000000000000000000"  # noqa: S105 — replay placeholder


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    """pytest-recording config — scrub auth + rewrite volatile headers.

    Cassette matching: method + scheme + host + path + query. Body is
    intentionally off the match set so a comment-body text tweak in a
    test doesn't force a re-record for reads.
    """
    return {
        "filter_headers": [
            ("authorization", "DUMMY"),
            ("x-github-request-id", None),
            ("set-cookie", None),
            ("cookie", None),
        ],
        "filter_query_parameters": ["access_token"],
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
        "decode_compressed_response": True,
        # record_mode is driven by CLI flag (`--record-mode`) — default
        # `none` in CI, `once` during `make record-integration`.
    }


@pytest.fixture
def gh_token(monkeypatch: pytest.MonkeyPatch) -> str:
    """Token for the adapter under test.

    Replay: the fake token is sufficient — VCR intercepts before the
    network call. Recording: expects `GITHUB_TOKEN` in the environment
    (the `make record-integration` target sets it via
    `gh auth token` or `create-github-app-token`).
    """
    import os  # noqa: PLC0415

    live = os.environ.get("GITHUB_TOKEN")
    if live and live.startswith(("ghs_", "ghp_", "github_pat_")):
        return live
    # Replay path: deterministic placeholder, also scrubbed on record.
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    return FAKE_TOKEN


@pytest.fixture
def smoke_repo() -> str:
    return SMOKE_REPO


@pytest.fixture(autouse=True)
def _silence_mlflow() -> Iterator[None]:
    """Integration tests don't touch MLflow — short-circuit the root
    autouse fixture's import cost by doing nothing extra here. Kept as a
    hook so we can add per-integration setup later without touching the
    root conftest.
    """
    yield
