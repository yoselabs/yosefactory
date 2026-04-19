"""GitHub App helper — mints App JWT + exchanges for installation tokens.

Installation tokens are short-lived (1h). We cache the current token in
memory and refresh on demand when we're within 5 minutes of expiry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt


def mint_app_jwt(*, app_id: int, private_key_pem: str, ttl_seconds: int = 540) -> str:
    """Mint a short-lived JWT for the GH App itself (max 10 min per GH policy)."""
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + ttl_seconds, "iss": app_id}
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


async def exchange_for_installation_token(
    *, http: httpx.AsyncClient, app_jwt: str, installation_id: int
) -> tuple[str, int]:
    """Exchange an App JWT for a short-lived installation token.

    Returns (token, expires_at_unix_seconds).
    """
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_jwt}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = await http.post(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    # GH returns expires_at as ISO8601; parse into unix seconds.
    from datetime import datetime

    expires_at = int(
        datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
    )
    return data["token"], expires_at


@dataclass
class _TokenCache:
    token: str = ""
    expires_at: int = 0


class GHAppClient:
    """Triggers workflow dispatches with an installation token that auto-refreshes."""

    _REFRESH_MARGIN = 300  # refresh if within 5 minutes of expiry

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        app_id: int,
        private_key_pem: str,
        installation_id: int,
        installation_token: str | None = None,
    ) -> None:
        self._http = http
        self._app_id = app_id
        self._pem = private_key_pem
        self._installation_id = installation_id
        self._cache = _TokenCache()
        if installation_token is not None:
            # Test path: far-future expiry so we never try to refresh.
            self._cache = _TokenCache(token=installation_token, expires_at=2**31 - 1)

    async def _current_token(self) -> str:
        now = int(time.time())
        if self._cache.token and now < self._cache.expires_at - self._REFRESH_MARGIN:
            return self._cache.token
        app_jwt = mint_app_jwt(app_id=self._app_id, private_key_pem=self._pem)
        token, expires_at = await exchange_for_installation_token(
            http=self._http, app_jwt=app_jwt, installation_id=self._installation_id
        )
        self._cache = _TokenCache(token=token, expires_at=expires_at)
        return token

    async def trigger_workflow_dispatch(
        self,
        *,
        repo: str,
        workflow_filename: str,
        ref: str,
        inputs: dict[str, Any],
    ) -> None:
        token = await self._current_token()
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_filename}/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        r = await self._http.post(
            url, json={"ref": ref, "inputs": inputs}, headers=headers
        )
        r.raise_for_status()
