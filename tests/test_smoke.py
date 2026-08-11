"""The scaffold's only claim: the package imports and the harness is reachable.

Deliberately thin. There is no application code yet — the two duplicated
workflows are session 1's job, and the substrate is extracted from their diff
(H572) rather than designed ahead of them. This test exists so `make check`
has something to fail on when the environment breaks.
"""


def test_package_imports() -> None:
    import a2factory

    assert a2factory is not None


def test_layers_exist() -> None:
    """The four layers are the structure, so their absence is a real failure."""
    import importlib

    for layer in ("protocol", "runtime", "server", "workflows"):
        assert importlib.import_module(f"a2factory.{layer}") is not None


def test_harness_is_importable() -> None:
    """claude-agent-sdk is the harness. If this breaks, nothing above it runs.

    It is NOT the Anthropic API SDK's `client.beta.messages.tool_runner` — a
    different package with a different scope. Asserting on `query` pins the
    one entry point the runtime will actually call.
    """
    from claude_agent_sdk import query

    assert callable(query)
