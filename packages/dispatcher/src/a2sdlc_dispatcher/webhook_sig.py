"""Webhook signature verification.

Jira Cloud sends a raw hex HMAC-SHA256 in X-Hub-Signature (when configured
with a shared secret). GitHub sends `sha256=<hex>` in X-Hub-Signature-256.
"""

from __future__ import annotations

import hashlib
import hmac


class SigError(Exception):
    pass


def verify_github_sig(*, body: bytes, header: str | None, secret: bytes) -> None:
    if not header:
        raise SigError("missing X-Hub-Signature-256 header")
    if not header.startswith("sha256="):
        raise SigError("malformed signature header")
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    given = header[len("sha256=") :]
    if not hmac.compare_digest(expected, given):
        raise SigError("signature mismatch")


def verify_jira_sig(*, body: bytes, header: str | None, secret: bytes) -> None:
    if not header:
        raise SigError("missing X-Hub-Signature header")
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header):
        raise SigError("signature mismatch")
