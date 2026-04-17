"""MCP server wiring for GEO.

Exposes one ``@server.list_tools()`` handler and one ``@server.call_tool()``
dispatcher. The MCP Python SDK registers *one* handler per request type,
not one per tool — ``func`` is invoked as ``func(tool_name, arguments)``.
An earlier rewrite called ``@server.call_tool()`` once per tool with a
single-argument handler, which meant every tool call silently routed to
the *last* registered function (``cleanup_downloads_tool``) and blew up
with an arg-count mismatch. All calls now go through :func:`handle_call_tool`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import mcp.types as types
from mcp.server import Server

from . import geo_downloader, geo_profiles

logger = logging.getLogger("geo-mcp-server")


async def handle_call_tool(
    name: str, arguments: Dict[str, Any]
) -> List[types.TextContent]:
    """Dispatch a tool call by name. Shared by the MCP and HTTP servers.

    Attribute lookups on ``geo_profiles`` / ``geo_downloader`` happen at
    call time so tests can monkeypatch the underlying functions.
    """
    arguments = arguments or {}

    if name == "search_geo":
        result: Any = await geo_profiles.search_geo(
            arguments.get("term", ""),
            arguments.get("retmax", 20),
            arguments.get("record_types"),
        )
    elif name == "search_geo_profiles":
        result = await geo_profiles.search_geo_profiles(
            arguments.get("term", ""), arguments.get("retmax", 20)
        )
    elif name == "search_geo_datasets":
        result = await geo_profiles.search_geo_datasets(
            arguments.get("term", ""), arguments.get("retmax", 20)
        )
    elif name == "search_geo_series":
        result = await geo_profiles.search_geo_series(
            arguments.get("term", ""), arguments.get("retmax", 20)
        )
    elif name == "search_geo_samples":
        result = await geo_profiles.search_geo_samples(
            arguments.get("term", ""), arguments.get("retmax", 20)
        )
    elif name == "search_geo_platforms":
        result = await geo_profiles.search_geo_platforms(
            arguments.get("term", ""), arguments.get("retmax", 20)
        )
    elif name == "download_geo_data":
        result = await geo_downloader.download_geo(
            arguments.get("geo_id", ""),
            arguments.get("db_type", "gse"),
            arguments.get("output_dir"),
        )
    elif name == "get_download_status":
        result = geo_downloader.get_download_status(
            arguments.get("geo_id", ""), arguments.get("db_type", "gse")
        )
    elif name == "list_downloaded_datasets":
        result = geo_downloader.list_downloaded_datasets(arguments.get("db_type"))
    elif name == "get_download_stats":
        result = geo_downloader.get_download_stats()
    elif name == "cleanup_downloads_tool":
        result = geo_downloader.cleanup_downloads(
            arguments.get("geo_id"), arguments.get("db_type")
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


class GEOMCPServer:
    """Owns the :class:`Server` instance and its tool registry."""

    def __init__(self) -> None:
        self.server: Server = Server("geo-mcp")
        self._register()

    def _register(self) -> None:
        @self.server.list_tools()
        async def _list_tools() -> List[types.Tool]:
            return self.get_tool_definitions()

        @self.server.call_tool()
        async def _call_tool(
            name: str, arguments: Dict[str, Any]
        ) -> List[types.TextContent]:
            return await handle_call_tool(name, arguments)

    def get_server(self) -> Server:
        return self.server

    def get_tool_definitions(self) -> List[types.Tool]:
        return [
            types.Tool(
                name="search_geo",
                description="Search GEO for all types of records (GSE, GSM, GPL, GDS)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": "Search term (e.g., 'breast cancer', 'GSE12345', 'RNA-seq')",
                        },
                        "retmax": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 20)",
                            "default": 20,
                        },
                        "record_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter for specific record types: GSE, GSM, GPL, GDS",
                        },
                    },
                    "required": ["term"],
                },
            ),
            types.Tool(
                name="search_geo_profiles",
                description="Search GEO Profiles database for gene expression profiles",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": "Search term for GEO Profiles",
                        },
                        "retmax": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 20)",
                            "default": 20,
                        },
                    },
                    "required": ["term"],
                },
            ),
            types.Tool(
                name="search_geo_datasets",
                description="Search GEO Datasets (GDS) - curated gene expression datasets",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": "Search term for GEO Datasets",
                        },
                        "retmax": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 20)",
                            "default": 20,
                        },
                    },
                    "required": ["term"],
                },
            ),
            types.Tool(
                name="search_geo_series",
                description="Search GEO Series (GSE) - complete experiments",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": "Search term for GEO Series",
                        },
                        "retmax": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 20)",
                            "default": 20,
                        },
                    },
                    "required": ["term"],
                },
            ),
            types.Tool(
                name="search_geo_samples",
                description="Search GEO Samples (GSM) - individual samples",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": "Search term for GEO Samples",
                        },
                        "retmax": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 20)",
                            "default": 20,
                        },
                    },
                    "required": ["term"],
                },
            ),
            types.Tool(
                name="search_geo_platforms",
                description="Search GEO Platforms (GPL) - array/sequencing platforms",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "term": {
                            "type": "string",
                            "description": "Search term for GEO Platforms",
                        },
                        "retmax": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 20)",
                            "default": 20,
                        },
                    },
                    "required": ["term"],
                },
            ),
            types.Tool(
                name="download_geo_data",
                description="Download GEO data files (SOFT format)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "geo_id": {
                            "type": "string",
                            "description": "GEO accession ID (e.g., GSE12345, GSM789, GPL456, GDS123)",
                        },
                        "db_type": {
                            "type": "string",
                            "description": "Database type: gse, gsm, gpl, or gds (default: gse)",
                            "default": "gse",
                        },
                        "output_dir": {
                            "type": "string",
                            "description": "Optional custom output directory",
                        },
                    },
                    "required": ["geo_id"],
                },
            ),
            types.Tool(
                name="get_download_status",
                description="Check if a GEO dataset has been downloaded",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string", "description": "GEO accession ID"},
                        "db_type": {
                            "type": "string",
                            "description": "Database type: gse, gsm, gpl, or gds (default: gse)",
                            "default": "gse",
                        },
                    },
                    "required": ["geo_id"],
                },
            ),
            types.Tool(
                name="list_downloaded_datasets",
                description="List all downloaded GEO datasets",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "db_type": {
                            "type": "string",
                            "description": "Optional filter by database type: gse, gsm, gpl, or gds",
                        }
                    },
                },
            ),
            types.Tool(
                name="get_download_stats",
                description="Get download statistics and limits",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="cleanup_downloads_tool",
                description="Clean up downloaded files",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "geo_id": {
                            "type": "string",
                            "description": "Optional specific GEO ID to remove",
                        },
                        "db_type": {
                            "type": "string",
                            "description": "Optional database type filter for cleanup",
                        },
                    },
                },
            ),
        ]


mcp_server = GEOMCPServer()
server = mcp_server.get_server()


async def handle_list_tools() -> List[types.Tool]:
    """Public symbol kept for ``mcp_http_server`` import compatibility."""
    return mcp_server.get_tool_definitions()
