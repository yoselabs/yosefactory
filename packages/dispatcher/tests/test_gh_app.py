from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from a2sdlc_dispatcher.gh_app import GHAppClient, mint_app_jwt


def _rsa_pem() -> str:
    """Generate a throwaway RSA key for JWT tests."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode()


def test_mint_app_jwt_with_int_app_id_does_not_raise():
    """Regression: PyJWT 2.x requires `iss` to be str; app_id is numeric env input."""
    pem = _rsa_pem()
    token = mint_app_jwt(app_id=12345, private_key_pem=pem)
    # Decode without verification to inspect claims.
    claims = pyjwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "12345"
    assert isinstance(claims["iss"], str)
    assert "iat" in claims
    assert "exp" in claims


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
