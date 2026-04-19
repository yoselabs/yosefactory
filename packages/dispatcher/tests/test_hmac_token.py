import pytest
from a2sdlc_dispatcher.hmac_token import mint_token, verify_token, TokenError

KEY = b"test-signing-key-32-bytes-long___"


def test_mint_then_verify_succeeds():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=60)
    claims = verify_token(token, key=KEY)
    assert claims.run_id == "run-123"
    assert claims.ticket_key == "A2X-42"


def test_expired_token_rejected():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=-1)
    with pytest.raises(TokenError, match="expired"):
        verify_token(token, key=KEY)


def test_tampered_signature_rejected():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=60)
    bad = token[:-4] + "XXXX"
    with pytest.raises(TokenError, match="signature"):
        verify_token(bad, key=KEY)


def test_wrong_key_rejected():
    token = mint_token("run-123", "A2X-42", key=KEY, ttl_seconds=60)
    with pytest.raises(TokenError):
        verify_token(token, key=b"different-key-also-32-bytes-long_")
