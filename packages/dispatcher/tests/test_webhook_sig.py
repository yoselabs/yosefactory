import hashlib
import hmac
import pytest
from a2sdlc_dispatcher.webhook_sig import verify_github_sig, verify_jira_sig, SigError

SECRET = b"shared-secret"


def gh_sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def test_github_valid():
    body = b'{"x":1}'
    verify_github_sig(body=body, header=gh_sig(body), secret=SECRET)  # should not raise


def test_github_invalid():
    body = b'{"x":1}'
    with pytest.raises(SigError):
        verify_github_sig(body=body, header="sha256=deadbeef", secret=SECRET)


def test_github_missing_header():
    with pytest.raises(SigError, match="missing"):
        verify_github_sig(body=b"{}", header=None, secret=SECRET)


def test_jira_valid():
    body = b'{"y":2}'
    sig = hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    verify_jira_sig(body=body, header=sig, secret=SECRET)


def test_jira_invalid():
    with pytest.raises(SigError):
        verify_jira_sig(body=b'{"y":2}', header="bogus", secret=SECRET)
