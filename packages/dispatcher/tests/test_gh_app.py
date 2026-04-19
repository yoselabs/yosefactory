from unittest.mock import AsyncMock, MagicMock
import pytest
from a2sdlc_dispatcher.gh_app import GHAppClient


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
