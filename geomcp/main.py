"""Entrypoint for the ``geo-mcp`` console script."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional


def _apply_cli_overrides(args: argparse.Namespace) -> None:
    """Push CLI flags into the downloader's runtime config."""
    from . import geo_downloader

    geo_downloader.configure(
        email=args.email,
        api_key=args.api_key,
        download_dir=args.download_dir,
        max_file_size_mb=args.max_file_size_mb,
        max_total_downloads_mb=args.max_total_downloads_mb,
        max_concurrent_downloads=args.max_concurrent_downloads,
        download_timeout_seconds=args.download_timeout_seconds,
        allowed_download_paths=args.allowed_download_paths,
    )


def run_http_server(host: str = "localhost", port: int = 8001) -> None:
    """Run the FastAPI HTTP wrapper."""
    import uvicorn

    from .mcp_http_server import app

    print(f"Starting HTTP server on http://{host}:{port}", file=sys.stderr)
    uvicorn.run(app, host=host, port=port)


async def run_mcp_server() -> None:
    """Run the MCP stdio server."""
    import mcp.server.stdio

    from .mcp_server import server

    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )
    except Exception as e:
        print(f"Error starting MCP server: {e}", file=sys.stderr)
        sys.exit(1)


def _default_config_path() -> Path:
    env_path = os.getenv("CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser()
    xdg_config = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    xdg_path = Path(xdg_config) / "geomcp" / "config.json"
    legacy_path = Path.home() / ".geo-mcp" / "config.json"
    # If an existing install already has config.json at the legacy location,
    # update it in place so `--init` doesn't orphan it.
    if legacy_path.exists() and not xdg_path.exists():
        return legacy_path
    return xdg_path


def setup_environment() -> None:
    """Deprecated: kept as a no-op for backward compatibility.

    Earlier versions of geo-mcp chdir'd into the package directory and
    copied a ``config_template.json`` on first run. Both behaviors were
    removed — config is now loaded lazily with sane XDG defaults — but
    the symbol is preserved so external launch scripts that import it
    still work.
    """
    return None


def init_config(config_path: Optional[Path] = None) -> bool:
    """Interactive helper that writes an XDG-compliant ``config.json``."""
    if config_path is None:
        config_path = _default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    print("GEO MCP Server Configuration Initialization")
    print("=" * 50)

    email = input("Enter your email address (required for NCBI E-utilities): ").strip()
    if not email:
        print("Error: Email address is required!", file=sys.stderr)
        return False

    api_key = input("Enter your NCBI API key (optional, press Enter to skip): ").strip()
    if not api_key:
        print("Note: Without an API key, you'll be limited to 3 requests/second")
    else:
        print("Note: With an API key, you'll have 10 requests/second")

    xdg_data = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    default_download_dir = str(Path(xdg_data) / "geomcp" / "downloads")

    config = {
        "base_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        "email": email,
        "api_key": api_key,
        "download_dir": default_download_dir,
        "max_file_size_mb": 5000,
        "max_total_downloads_mb": 10000,
        "max_concurrent_downloads": 3,
        "download_timeout_seconds": 300,
        "allowed_download_paths": [default_download_dir],
    }

    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
    except OSError as e:
        print(f"Error creating config file: {e}", file=sys.stderr)
        return False

    print(f"\nConfiguration file created at: {config_path}")
    print("\nYou can now run the server with:")
    print("  geo-mcp              # MCP stdio server")
    print("  geo-mcp --http       # HTTP server on localhost:8001")
    print("\nClaude Desktop configuration snippet:")
    print(
        json.dumps(
            {
                "mcpServers": {
                    "geo-mcp": {
                        "command": "geo-mcp",
                        "env": {"CONFIG_PATH": str(config_path)},
                    }
                }
            },
            indent=2,
        )
    )
    return True


def main() -> None:
    """Parse CLI flags and dispatch to the stdio or HTTP server."""
    parser = argparse.ArgumentParser(
        description="GEO MCP Server - Access GEO data through Model Context Protocol",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  geo-mcp --init                                     # Create a config.json interactively
  geo-mcp                                            # Run MCP stdio server
  geo-mcp --http                                     # Run HTTP server on localhost:8001
  geo-mcp --http --host 0.0.0.0 --port 8080          # Run HTTP server on all interfaces
  GEOMCP_EMAIL=you@example.org geo-mcp               # Configure via environment variable
  geo-mcp --email you@example.org                    # Configure via CLI flag
        """,
    )

    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize configuration file with interactive prompts",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run HTTP server instead of MCP stdio server",
    )
    parser.add_argument("--host", default="localhost", help="HTTP server host")
    parser.add_argument("--port", type=int, default=8001, help="HTTP server port")

    # Config overrides. Defaults are None so that unset flags fall through to
    # env vars and then config.json inside geo_downloader.configure().
    parser.add_argument("--email", help="Email address for NCBI E-utilities")
    parser.add_argument(
        "--api-key", dest="api_key", help="NCBI API key for higher rate limits"
    )
    parser.add_argument(
        "--download-dir",
        dest="download_dir",
        help="Directory where downloads will be stored",
    )
    parser.add_argument(
        "--max-file-size-mb",
        dest="max_file_size_mb",
        type=int,
        help="Maximum size of individual files to download, in MB",
    )
    parser.add_argument(
        "--max-total-downloads-mb",
        dest="max_total_downloads_mb",
        type=int,
        help="Maximum total size of all downloads, in MB",
    )
    parser.add_argument(
        "--max-concurrent-downloads",
        dest="max_concurrent_downloads",
        type=int,
        help="Maximum number of concurrent downloads",
    )
    parser.add_argument(
        "--download-timeout-seconds",
        dest="download_timeout_seconds",
        type=int,
        help="Timeout for download requests, in seconds",
    )
    parser.add_argument(
        "--allowed-download-paths",
        dest="allowed_download_paths",
        nargs="+",
        help="List of absolute paths permitted as download targets",
    )
    # Deprecated, kept for backward compatibility with pre-0.1.2 command lines.
    parser.add_argument(
        "--retmax",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    from . import __version__

    parser.add_argument("--version", action="version", version=f"geo-mcp {__version__}")

    args = parser.parse_args()

    if args.init:
        sys.exit(0 if init_config() else 1)

    _apply_cli_overrides(args)

    if args.http:
        run_http_server(args.host, args.port)
    else:
        asyncio.run(run_mcp_server())


if __name__ == "__main__":
    main()
