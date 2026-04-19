"""Per-run HMAC capability tokens.

Token format: base64url(payload || "|" || sig)
  payload = run_id || "|" || ticket_key || "|" || exp
  sig     = HMAC-SHA256(key, payload).hexdigest()

Scope: single run, single 24h window (configurable per mint). Cannot be
replayed for other tickets and cannot be refreshed — mint a fresh one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass


class TokenError(Exception):
    """Raised on any verification failure (signature, expiry, format)."""


@dataclass(frozen=True)
class TokenClaims:
    run_id: str
    ticket_key: str
    exp: int


def _sign(payload: str, key: bytes) -> str:
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def mint_token(
    run_id: str, ticket_key: str, *, key: bytes, ttl_seconds: int = 86400
) -> str:
    exp = int(time.time()) + ttl_seconds
    payload = f"{run_id}|{ticket_key}|{exp}"
    sig = _sign(payload, key)
    raw = f"{payload}|{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_token(token: str, *, key: bytes) -> TokenClaims:
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as e:
        raise TokenError(f"malformed token: {e}") from None
    try:
        raw = decoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise TokenError("bad signature") from None
    parts = raw.split("|")
    if len(parts) != 4:
        raise TokenError("malformed payload")
    run_id, ticket_key, exp_s, sig = parts
    payload = f"{run_id}|{ticket_key}|{exp_s}"
    expected = _sign(payload, key)
    if not hmac.compare_digest(sig, expected):
        raise TokenError("bad signature")
    try:
        exp = int(exp_s)
    except ValueError:
        raise TokenError("bad expiry") from None
    if exp < int(time.time()):
        raise TokenError("expired")
    return TokenClaims(run_id=run_id, ticket_key=ticket_key, exp=exp)
