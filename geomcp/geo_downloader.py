"""GEO data downloader backed by the NCBI E-utilities HTTPS endpoint.

Public API
----------
    download_geo(acc, db_type, out_dir=None)      -> dict
    get_download_status(geo_id, db_type)          -> dict
    list_downloaded_datasets(db_type=None)        -> dict
    get_download_stats()                          -> dict
    cleanup_downloads(geo_id=None, db_type=None)  -> dict
    configure(**overrides)                        -> None

Config resolution, highest wins
-------------------------------
    1. configure(...) runtime overrides (how the CLI wires in --flags)
    2. GEOMCP_* environment variables
    3. config.json at $CONFIG_PATH, $XDG_CONFIG_HOME/geomcp/config.json,
       or ~/.geo-mcp/config.json (legacy fallback)
    4. Built-in defaults

Nothing in this module touches the filesystem, env, or network at import
time — a prior version called sys.exit(1) from module scope when config.json
was missing, which broke pytest, mypy, and any code that merely imported the
package without a pre-existing config.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiofiles
import aiohttp

BYTES_IN_MB = 1024 * 1024

_ENV_MAP = {
    "GEOMCP_EMAIL": "email",
    "GEOMCP_API_KEY": "api_key",
    "GEOMCP_BASE_URL": "base_url",
    "GEOMCP_DOWNLOAD_DIR": "download_dir",
}

_CONFIG_OVERRIDES: Dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def _xdg_data_home() -> Path:
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _xdg_config_home() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")


def _default_download_dir() -> Path:
    return _xdg_data_home() / "geomcp" / "downloads"


def _config_search_paths() -> List[Path]:
    paths: List[Path] = []
    env_path = os.getenv("CONFIG_PATH")
    if env_path:
        paths.append(Path(os.path.expanduser(env_path)))
    paths.append(_xdg_config_home() / "geomcp" / "config.json")
    paths.append(Path.home() / ".geo-mcp" / "config.json")  # legacy
    return paths


def _hardcoded_defaults() -> Dict[str, Any]:
    return {
        "base_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        "email": None,
        "api_key": "",
        "download_dir": str(_default_download_dir()),
        "max_file_size_mb": 5000,
        "max_total_downloads_mb": 10000,
        "max_concurrent_downloads": 3,
        "download_timeout_seconds": 300,
        "allowed_download_paths": None,  # None => [download_dir]
    }


@lru_cache(maxsize=1)
def _config() -> Dict[str, Any]:
    cfg = _hardcoded_defaults()

    for path in _config_search_paths():
        if path.exists():
            try:
                with open(path) as f:
                    cfg.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                pass
            break

    for env_key, cfg_key in _ENV_MAP.items():
        val = os.getenv(env_key)
        if val is not None and val != "":
            cfg[cfg_key] = val

    cfg.update(_CONFIG_OVERRIDES)
    return cfg


def configure(**overrides: Any) -> None:
    """Apply runtime config overrides; takes precedence over env and config.json.

    Values of ``None`` are ignored so argparse defaults don't clobber lower
    layers when the user never passed the flag.
    """
    for k, v in overrides.items():
        if v is not None:
            _CONFIG_OVERRIDES[k] = v
    _config.cache_clear()


def _require_email() -> str:
    email = _config().get("email")
    if not email:
        raise RuntimeError(
            "NCBI requires an email address for E-utilities. Set GEOMCP_EMAIL, "
            "pass --email on the CLI, or run `geo-mcp --init` to create "
            f"{_xdg_config_home() / 'geomcp' / 'config.json'}."
        )
    return str(email)


# --------------------------------------------------------------------------- #
# Paths & filesystem helpers
# --------------------------------------------------------------------------- #


def _download_root() -> Path:
    return Path(_config()["download_dir"]).expanduser().resolve()


def _allowed_roots() -> List[Path]:
    allowed = _config().get("allowed_download_paths")
    if not allowed:
        return [_download_root()]
    return [Path(p).expanduser().resolve() for p in allowed]


def _is_child(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _allowed(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    for root in _allowed_roots():
        if resolved == root or _is_child(resolved, root):
            return True
    return False


def _dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _disk_free(p: Path) -> int:
    try:
        check = p if p.exists() else p.parent
        return shutil.disk_usage(check).free
    except OSError:
        return 0


# --------------------------------------------------------------------------- #
# URL extraction
# --------------------------------------------------------------------------- #
#
# NCBI retired its anonymous FTP endpoint in 2024; E-utilities XML now
# returns https:// URLs rooted at ftp.ncbi.nlm.nih.gov. The previous regex
# only matched ``ftp://`` and silently dropped every modern response,
# producing spurious "no downloadable SOFT file exposed" errors.

_URL_RE = re.compile(r"(?:ftp|https?)://[\w./-]+", re.IGNORECASE)
_ACC_RE = re.compile(r"/(GSE\d+|GSM\d+|GPL\d+|GDS\d+)/?$", re.IGNORECASE)
_FILE_SUFFIXES = (
    ".soft.gz",
    ".txt.gz",
    ".tar",
    ".tar.gz",
    ".csv.gz",
    ".tsv.gz",
)


def _extract_download_urls(xml_text: str) -> List[str]:
    """Return HTTPS direct links to SOFT archives, normalised from E-utils XML.

    Accepts both ``ftp://`` and ``https://`` schemes on
    ``ftp.ncbi.nlm.nih.gov``. When a URL points at an accession directory
    (e.g. ``.../GSE10nnn/GSE10072``) rather than a concrete file, the
    conventional SOFT archive path beneath it is appended.
    """
    out: List[str] = []
    seen: Set[str] = set()

    for raw in _URL_RE.findall(xml_text):
        link = raw.rstrip("/")
        if link.lower().startswith("ftp://"):
            link = "https://" + link[len("ftp://") :]

        low = link.lower()
        if low.endswith(_FILE_SUFFIXES):
            if link not in seen:
                out.append(link)
                seen.add(link)
            continue

        m = _ACC_RE.search(link)
        if not m:
            continue
        acc = m.group(1).upper()
        if acc.startswith("GSE"):
            soft = f"{link}/soft/{acc}_family.soft.gz"
        else:
            soft = f"{link}/soft/{acc}.soft.gz"
        if soft not in seen:
            out.append(soft)
            seen.add(soft)

    return out


# --------------------------------------------------------------------------- #
# E-utilities (async)
# --------------------------------------------------------------------------- #


async def _eutils_get(
    session: aiohttp.ClientSession, path: str, params: Dict[str, str]
) -> str:
    cfg = _config()
    q = dict(params)
    q["email"] = _require_email()
    api_key = cfg.get("api_key") or ""
    if api_key:
        q["api_key"] = api_key
    url = f"{str(cfg['base_url']).rstrip('/')}/{path}"
    async with session.get(url, params=q) as resp:
        resp.raise_for_status()
        return await resp.text()


async def _esearch_uid(session: aiohttp.ClientSession, acc: str) -> Optional[str]:
    body = await _eutils_get(
        session,
        "esearch.fcgi",
        {"db": "gds", "term": f"{acc}[ACCN]", "retmode": "json", "retmax": "1"},
    )
    data = json.loads(body)
    ids = data.get("esearchresult", {}).get("idlist", [])
    return ids[0] if ids else None


async def _efetch_gds(session: aiohttp.ClientSession, uid: str) -> str:
    return await _eutils_get(
        session, "efetch.fcgi", {"db": "gds", "id": uid, "retmode": "xml"}
    )


# --------------------------------------------------------------------------- #
# Per-event-loop semaphore
# --------------------------------------------------------------------------- #
#
# A module-level ``asyncio.Semaphore`` captures whatever loop happens to be
# running when the module is first imported and then raises
# "attached to a different loop" under the MCP stdio runtime. Bind one
# semaphore per event loop instead.

_loop_semaphores: "Dict[int, asyncio.Semaphore]" = {}


def _get_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    sem = _loop_semaphores.get(key)
    if sem is None:
        sem = asyncio.Semaphore(int(_config()["max_concurrent_downloads"]))
        _loop_semaphores[key] = sem
    return sem


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def download_geo(
    acc: str, db_type: str, out_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Download the SOFT archive(s) for a GEO accession via NCBI E-utilities."""
    cfg = _config()
    root = _download_root()
    max_file_bytes = int(cfg["max_file_size_mb"]) * BYTES_IN_MB
    max_total_bytes = int(cfg["max_total_downloads_mb"]) * BYTES_IN_MB
    timeout = aiohttp.ClientTimeout(total=int(cfg["download_timeout_seconds"]))

    dest = Path(out_dir) if out_dir else root / db_type / acc
    dest = dest.expanduser().resolve()
    if not _allowed(dest):
        raise ValueError(
            f"output dir {dest} is outside allowed_download_paths "
            f"{[str(p) for p in _allowed_roots()]}"
        )
    dest.mkdir(parents=True, exist_ok=True)

    if _dir_size(root) >= max_total_bytes:
        raise ValueError("total download limit reached")

    semaphore = _get_semaphore()

    async with semaphore:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            uid = await _esearch_uid(session, acc)
            if not uid:
                raise ValueError(f"{acc} not found in GDS database")
            xml = await _efetch_gds(session, uid)
            urls = _extract_download_urls(xml)
            if not urls:
                raise ValueError(
                    f"no downloadable archive found for {acc} in E-utils XML"
                )

            downloaded: List[str] = []
            total_bytes = 0

            for url in urls:
                filename = url.rsplit("/", 1)[-1]
                filepath = dest / filename

                if _disk_free(dest) < max_file_bytes * 2:
                    raise ValueError("insufficient disk space to continue")

                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise ValueError(
                            f"download failed with HTTP {resp.status}: {url}"
                        )
                    clen = int(resp.headers.get("content-length", "0"))
                    if clen and clen > max_file_bytes:
                        raise ValueError(
                            f"{filename} advertises {clen} bytes, exceeds max_file_size_mb"
                        )

                    size = 0
                    async with aiofiles.open(filepath, "wb") as fh:
                        async for chunk in resp.content.iter_chunked(8192):
                            size += len(chunk)
                            if size > max_file_bytes:
                                raise ValueError(
                                    f"{filename} grew beyond max_file_size_mb mid-transfer"
                                )
                            await fh.write(chunk)
                    total_bytes += size
                    downloaded.append(str(filepath))

            meta_path = dest / f"{acc}_metadata.xml"
            meta_path.write_text(xml)
            downloaded.append(str(meta_path))

    return {
        "acc": acc,
        "db_type": db_type,
        "output_dir": str(dest),
        "files": downloaded,
        "total_size_mb": round(total_bytes / BYTES_IN_MB, 2),
    }


# --------------------------------------------------------------------------- #
# Status / cleanup helpers
# --------------------------------------------------------------------------- #


def get_download_status(geo_id: str, db_type: str) -> Dict[str, Any]:
    """Check whether a GEO dataset has been downloaded."""
    try:
        dataset_path = _download_root() / db_type / geo_id
        if dataset_path.exists():
            files = list(dataset_path.glob("*"))
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            return {
                "geo_id": geo_id,
                "db_type": db_type,
                "downloaded": True,
                "path": str(dataset_path),
                "files": [f.name for f in files],
                "total_size_mb": round(total_size / BYTES_IN_MB, 2),
            }
        return {
            "geo_id": geo_id,
            "db_type": db_type,
            "downloaded": False,
            "path": str(dataset_path),
        }
    except OSError as e:
        return {
            "geo_id": geo_id,
            "db_type": db_type,
            "downloaded": False,
            "error": str(e),
        }


def list_downloaded_datasets(db_type: Optional[str] = None) -> Dict[str, Any]:
    """List all downloaded datasets, optionally filtered by database type."""
    try:
        root = _download_root()
        datasets: List[Dict[str, str]] = []
        if not root.exists():
            return {"datasets": [], "count": 0}
        if db_type:
            db_path = root / db_type
            if db_path.exists():
                for d in db_path.iterdir():
                    if d.is_dir():
                        datasets.append(
                            {"geo_id": d.name, "db_type": db_type, "path": str(d)}
                        )
        else:
            for db_dir in root.iterdir():
                if db_dir.is_dir():
                    for d in db_dir.iterdir():
                        if d.is_dir():
                            datasets.append(
                                {
                                    "geo_id": d.name,
                                    "db_type": db_dir.name,
                                    "path": str(d),
                                }
                            )
        return {"datasets": datasets, "count": len(datasets)}
    except OSError as e:
        return {"error": str(e), "datasets": [], "count": 0}


def get_download_stats() -> Dict[str, Any]:
    """Return overall download statistics and configured limits."""
    cfg = _config()
    try:
        root = _download_root()
        total_size = _dir_size(root)
        return {
            "download_dir": str(root),
            "total_downloaded_mb": round(total_size / BYTES_IN_MB, 2),
            "max_total_mb": int(cfg["max_total_downloads_mb"]),
            "max_file_mb": int(cfg["max_file_size_mb"]),
            "max_concurrent": int(cfg["max_concurrent_downloads"]),
            "timeout_seconds": int(cfg["download_timeout_seconds"]),
            "allowed_paths": [str(p) for p in _allowed_roots()],
            "disk_free_mb": round(_disk_free(root) / BYTES_IN_MB, 2),
        }
    except OSError as e:
        return {"error": str(e), "download_dir": str(_download_root())}


def cleanup_downloads(
    geo_id: Optional[str] = None, db_type: Optional[str] = None
) -> Dict[str, Any]:
    """Remove downloaded files."""
    try:
        root = _download_root()
        removed: List[str] = []
        if geo_id and db_type:
            p = root / db_type / geo_id
            if p.exists():
                shutil.rmtree(p)
                removed.append(str(p))
        elif db_type:
            p = root / db_type
            if p.exists():
                for d in p.iterdir():
                    if d.is_dir():
                        shutil.rmtree(d)
                        removed.append(str(d))
        else:
            if root.exists():
                shutil.rmtree(root)
                removed.append(str(root))
        return {"removed": removed, "count": len(removed)}
    except OSError as e:
        return {"error": str(e), "removed": [], "count": 0}


# --------------------------------------------------------------------------- #
# Minimal CLI (for ad-hoc debugging; the shipped entrypoint is geomcp.main)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Download a GEO SOFT archive via NCBI E-utilities"
    )
    parser.add_argument("acc", nargs="?", default="GSE10072")
    parser.add_argument("--db", default="gse")
    parser.add_argument("--email", help="NCBI email (overrides config)")
    args = parser.parse_args()

    if args.email:
        configure(email=args.email)

    try:
        result = asyncio.run(download_geo(args.acc, args.db))
        print(json.dumps(result, indent=2))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Backward-compatibility aliases
# --------------------------------------------------------------------------- #
#
# Kept so any external script or fork that imported the pre-rewrite private
# names keeps working. All new code should use the names above.

_extract_ftp_links = _extract_download_urls


def _load_config() -> Dict[str, Any]:
    """Deprecated: use :func:`_config` instead."""
    return _config()
