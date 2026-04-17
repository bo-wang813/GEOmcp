"""GEO MCP Server — Model Context Protocol access to NCBI's Gene Expression Omnibus."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .geo_downloader import download_geo
from .geo_profiles import search_geo, search_geo_datasets, search_geo_profiles
from .main import main

try:
    __version__ = _pkg_version("geo-mcp")
except PackageNotFoundError:  # editable install without metadata
    __version__ = "0.0.0+unknown"

__author__ = "MCPmed Contributors"
__email__ = "matthias.flotho@ccb.uni-saarland.de"

__all__ = [
    "__version__",
    "main",
    "search_geo",
    "search_geo_profiles",
    "search_geo_datasets",
    "download_geo",
]
