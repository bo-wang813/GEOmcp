"""Regression tests for the MCP server wiring.

These exist to pin down the tool-dispatch bug where
``GEOMCPServer._setup_tools`` called ``@self.server.call_tool()`` once
per tool with a single-argument handler:

- The MCP SDK registers *one* handler for ``CallToolRequest``; each call
  of the decorator replaced the previous registration, so every tool
  call silently routed to the last-defined function
  (``cleanup_downloads_tool``).
- The SDK invokes the handler as ``func(tool_name, arguments)``; the old
  handlers took one argument, so every call blew up with
  "takes 1 positional argument but 2 were given".
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import pytest


@pytest.fixture
def mcp_env(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-export clean_env plus a valid email so search helpers don't refuse."""
    monkeypatch.setenv("GEOMCP_EMAIL", "test@example.org")


def _stub_async(value: Any) -> Callable[..., Awaitable[Any]]:
    async def _fn(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _fn


def _stub_sync(value: Any) -> Callable[..., Any]:
    def _fn(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _fn


@pytest.mark.asyncio
async def test_dispatch_covers_every_registered_tool(
    mcp_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every tool advertised by get_tool_definitions must dispatch cleanly.

    Without this, re-introducing a per-tool ``@server.call_tool()`` loop
    would route every tool to whichever function was registered last and
    the test would surface it by raising ``ValueError: Unknown tool``.
    """
    from geomcp import geo_downloader, geo_profiles
    from geomcp.mcp_server import handle_call_tool, mcp_server

    for fn_name in (
        "search_geo",
        "search_geo_profiles",
        "search_geo_datasets",
        "search_geo_series",
        "search_geo_samples",
        "search_geo_platforms",
    ):
        monkeypatch.setattr(geo_profiles, fn_name, _stub_async({"stubbed": fn_name}))

    monkeypatch.setattr(
        geo_downloader, "download_geo", _stub_async({"stubbed": "download_geo"})
    )
    monkeypatch.setattr(
        geo_downloader,
        "get_download_status",
        _stub_sync({"stubbed": "status"}),
    )
    monkeypatch.setattr(
        geo_downloader,
        "list_downloaded_datasets",
        _stub_sync({"stubbed": "list"}),
    )
    monkeypatch.setattr(
        geo_downloader,
        "get_download_stats",
        _stub_sync({"stubbed": "stats"}),
    )
    monkeypatch.setattr(
        geo_downloader,
        "cleanup_downloads",
        _stub_sync({"stubbed": "cleanup"}),
    )

    tool_names = [t.name for t in mcp_server.get_tool_definitions()]
    assert tool_names, "no tools registered"

    sample_args = {
        "term": "cancer",
        "retmax": 5,
        "geo_id": "GSE10072",
        "db_type": "gse",
    }

    for name in tool_names:
        out = await handle_call_tool(name, sample_args)
        assert len(out) == 1, f"{name} returned {len(out)} content blocks"
        assert out[0].type == "text"
        assert out[0].text, f"{name} returned empty text"


@pytest.mark.asyncio
async def test_unknown_tool_name_raises(mcp_env: None) -> None:
    from geomcp.mcp_server import handle_call_tool

    with pytest.raises(ValueError, match="Unknown tool"):
        await handle_call_tool("not_a_real_tool", {})


def test_call_tool_handler_accepts_name_and_arguments(mcp_env: None) -> None:
    """The SDK invokes the registered call_tool handler with (name, arguments).

    The original bug was that the handlers took only ``(arguments)``.
    Guard against a regression by inspecting the registered handler's
    signature through the server's internal request handler map.
    """
    import inspect

    import mcp.types as mcp_types

    from geomcp.mcp_server import server

    handler = server.request_handlers.get(mcp_types.CallToolRequest)
    assert handler is not None, "no CallToolRequest handler registered"

    # The SDK wraps the user function in a closure; reach through the
    # closure to pull the original coroutine function out so we can
    # check its signature.
    user_fn = None
    for cell in getattr(handler, "__closure__", None) or ():
        contents = cell.cell_contents
        if inspect.iscoroutinefunction(contents):
            user_fn = contents
            break

    assert user_fn is not None, "could not locate the registered user handler"
    params = list(inspect.signature(user_fn).parameters.values())
    # Exclude *self* if the handler was a bound method
    positional = [
        p
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    assert (
        len(positional) == 2
    ), f"expected (name, arguments); got {[p.name for p in positional]}"
