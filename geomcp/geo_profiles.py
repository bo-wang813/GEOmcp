"""Async NCBI E-utilities search wrappers for GEO.

All top-level ``search_*`` coroutines hit
``https://eutils.ncbi.nlm.nih.gov/entrez/eutils`` and return JSON. Config
(base URL, email, API key) is shared with :mod:`geo_downloader` — see the
precedence doc in that module.

These used to be blocking ``requests`` calls with a ``time.sleep(0.1)``
politeness delay, which stalled the MCP stdio event loop on every tool
invocation. They are now non-blocking ``aiohttp`` calls.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import aiohttp

from .geo_downloader import _config, _require_email

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
# NCBI allows 3 req/sec without a key, 10 with. A small await keeps us well
# under the threshold when the MCP client fires tools back-to-back.
_POLITE_SLEEP_SECONDS = 0.1


def _empty_categorized() -> Dict[str, Any]:
    return {
        "total_count": 0,
        "results": [],
        "series": [],
        "samples": [],
        "platforms": [],
        "datasets": [],
    }


def _empty_summary() -> Dict[str, Any]:
    return {"esummaryresult": ["Empty id list - nothing todo"]}


def _typed_wrap(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Emulate the legacy esummary wire shape for typed-subset searches."""
    if not records:
        return _empty_summary()
    result: Dict[str, Any] = {"uids": [r.get("uid") for r in records]}
    for record in records:
        uid = record.get("uid")
        if uid:
            result[uid] = record
    return {"header": {"type": "esummary", "version": "0.3"}, "result": result}


async def _eutils(
    session: aiohttp.ClientSession, path: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    cfg = _config()
    q: Dict[str, Any] = {**params, "retmode": "json", "email": _require_email()}
    api_key = cfg.get("api_key") or ""
    if api_key:
        q["api_key"] = api_key
    url = f"{str(cfg['base_url']).rstrip('/')}/{path}"
    await asyncio.sleep(_POLITE_SLEEP_SECONDS)
    async with session.get(url, params=q) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _esearch(
    session: aiohttp.ClientSession, db: str, term: str, retmax: int
) -> Dict[str, Any]:
    return await _eutils(
        session, "esearch.fcgi", {"db": db, "term": term, "retmax": retmax}
    )


async def _esummary(
    session: aiohttp.ClientSession, db: str, ids: List[str]
) -> Dict[str, Any]:
    if not ids:
        return {"result": {}}
    return await _eutils(
        session, "esummary.fcgi", {"db": db, "id": ",".join(map(str, ids))}
    )


async def search_geo(
    term: str, retmax: int = 20, record_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Search the GDS database and return results bucketed by accession type."""
    try:
        async with aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT) as session:
            data = await _esearch(session, "gds", term, retmax)
            ids = data.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return _empty_categorized()
            summaries = await _esummary(session, "gds", ids)

        records = summaries.get("result", {})
        categorized = _empty_categorized()
        categorized["total_count"] = len(ids)

        for uid in ids:
            record = records.get(uid)
            if not record:
                continue
            accession = record.get("accession", "")
            categorized["results"].append(record)
            if accession.startswith("GSE"):
                categorized["series"].append(record)
            elif accession.startswith("GSM"):
                categorized["samples"].append(record)
            elif accession.startswith("GPL"):
                categorized["platforms"].append(record)
            elif accession.startswith("GDS"):
                categorized["datasets"].append(record)

        if record_types:
            wanted = {rt.upper() for rt in record_types}
            filtered: List[Dict[str, Any]] = []
            for rt, key in (
                ("GSE", "series"),
                ("GSM", "samples"),
                ("GPL", "platforms"),
                ("GDS", "datasets"),
            ):
                if rt in wanted:
                    filtered.extend(categorized[key])
            categorized["results"] = filtered
            categorized["total_count"] = len(filtered)

        return categorized

    except Exception as exc:
        out = _empty_categorized()
        out["error"] = str(exc)
        return out


async def search_geo_profiles(term: str, retmax: int = 20) -> Dict[str, Any]:
    """Search the separate ``geoprofiles`` E-utilities database."""
    try:
        async with aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT) as session:
            data = await _esearch(session, "geoprofiles", term, retmax)
            ids = data.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return _empty_summary()
            return await _esummary(session, "geoprofiles", ids)
    except Exception as exc:
        out = _empty_summary()
        out["error"] = str(exc)
        return out


async def search_geo_datasets(term: str, retmax: int = 20) -> Dict[str, Any]:
    """Search GDS records only (curated datasets)."""
    try:
        result = await search_geo(term, retmax, record_types=["GDS"])
        return _typed_wrap(result.get("datasets", []))
    except Exception as exc:
        out = _empty_summary()
        out["error"] = str(exc)
        return out


async def search_geo_series(term: str, retmax: int = 20) -> Dict[str, Any]:
    """Search GSE records only (submitter series)."""
    try:
        result = await search_geo(term, retmax, record_types=["GSE"])
        return _typed_wrap(result.get("series", []))
    except Exception as exc:
        out = _empty_summary()
        out["error"] = str(exc)
        return out


async def search_geo_samples(term: str, retmax: int = 20) -> Dict[str, Any]:
    """Search GSM records only (individual samples)."""
    try:
        result = await search_geo(term, retmax, record_types=["GSM"])
        return _typed_wrap(result.get("samples", []))
    except Exception as exc:
        out = _empty_summary()
        out["error"] = str(exc)
        return out


async def search_geo_platforms(term: str, retmax: int = 20) -> Dict[str, Any]:
    """Search GPL records only (array/sequencing platform definitions)."""
    try:
        result = await search_geo(term, retmax, record_types=["GPL"])
        return _typed_wrap(result.get("platforms", []))
    except Exception as exc:
        out = _empty_summary()
        out["error"] = str(exc)
        return out
