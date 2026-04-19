from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from a2sdlc_dispatcher.gh_app import GHAppClient


def _rsa_pem() -> str:
    """Generate a throwaway RSA key for JWT tests."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode()


@pytest.mark.asyncio
async def test_trigger_workflow_dispatch_calls_right_endpoint():
    http = AsyncMock()
    http.post.return_value = MagicMock(status_code=204)

    client = GHAppClient(
        http=http,
        app_id=1,
        private_key_pem="dummy",
        installation_id=1,
        installation_token="ghs_xxx",
    )
    await client.trigger_workflow_dispatch(
        repo="acme/webapp",
        workflow_filename="a2sdlc-split.yml",
        ref="main",
        inputs={"ticket_key": "A2X-42", "run_id": "r1"},
    )

    http.post.assert_awaited_once()
    url = http.post.await_args.args[0]
    assert (
        url
        == "https://api.github.com/repos/acme/webapp/actions/workflows/a2sdlc-split.yml/dispatches"
    )
    body = http.post.await_args.kwargs["json"]
    assert body["ref"] == "main"
    assert body["inputs"]["ticket_key"] == "A2X-42"
    assert http.post.await_args.kwargs["headers"]["Authorization"] == "Bearer ghs_xxx"


@pytest.mark.asyncio
async def test_trigger_workflow_dispatch_mints_jwt_and_exchanges_token():
    """Exercise the full _current_token path: mint_app_jwt(int app_id) →
    exchange_for_installation_token → dispatch. The other test uses the
    `installation_token=` backdoor and bypasses JWT mint entirely — which
    is exactly how the PyJWT 2.x `iss` type bug slipped past unit tests."""
    pem = _rsa_pem()

    # Two POST calls: first to /access_tokens, second to /dispatches.
    exchange_response = MagicMock()
    exchange_response.raise_for_status = MagicMock()
    exchange_response.json.return_value = {
        "token": "ghs_minted",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    dispatch_response = MagicMock(status_code=204)
    dispatch_response.raise_for_status = MagicMock()

    http = AsyncMock(spec=httpx.AsyncClient)
    http.post.side_effect = [exchange_response, dispatch_response]

    client = GHAppClient(
        http=http,
        app_id=12345,
        private_key_pem=pem,
        installation_id=999,
    )
    await client.trigger_workflow_dispatch(
        repo="acme/webapp",
        workflow_filename="a2sdlc-split.yml",
        ref="main",
        inputs={"ticket_key": "A2X-42"},
    )

    assert http.post.await_count == 2
    # 1st call: exchange URL uses installation_id, Authorization is App JWT.
    exchange_call = http.post.await_args_list[0]
    assert (
        exchange_call.args[0]
        == "https://api.github.com/app/installations/999/access_tokens"
    )
    app_jwt = exchange_call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
    claims = pyjwt.decode(app_jwt, options={"verify_signature": False})
    assert claims["iss"] == "12345"  # str, not int — the bug we're regressing

    # 2nd call: dispatch uses the minted installation token.
    dispatch_call = http.post.await_args_list[1]
    assert (
        dispatch_call.args[0]
        == "https://api.github.com/repos/acme/webapp/actions/workflows/a2sdlc-split.yml/dispatches"
    )
    assert dispatch_call.kwargs["headers"]["Authorization"] == "Bearer ghs_minted"
