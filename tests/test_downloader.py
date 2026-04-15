"""Regression tests for the Tier A download pipeline fixes.

These exist primarily to pin down the two bugs that were silently breaking
downloads in the wild:

1. ``geo_downloader`` imported config at module load time and called
   ``sys.exit(1)`` if it was missing or incomplete. That broke pytest,
   mypy, and any environment without a pre-existing ``config.json``.

2. The URL extractor used ``re.findall(r"ftp://[\\w./-]+", ...)`` which
   silently dropped every E-utils response after NCBI migrated from FTP
   to HTTPS in 2024, producing spurious "no downloadable SOFT file" errors.
"""

from __future__ import annotations

import pytest


def test_package_imports_without_config(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    assert callable(d.download_geo)
    assert callable(d.configure)
    assert callable(d._extract_download_urls)


def test_mcp_server_imports_without_config(clean_env: None) -> None:
    """The MCP server module imports geo_downloader at load time."""
    import geomcp.mcp_server  # noqa: F401 — importing is the assertion


def test_missing_email_errors_only_on_use(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    with pytest.raises(RuntimeError, match="email"):
        d._require_email()


def test_extract_urls_accepts_ftp_scheme(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    xml = (
        '<ExtRelation relationship="reanalysis">'
        "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE10nnn/GSE10072/"
        "</ExtRelation>"
    )
    urls = d._extract_download_urls(xml)
    assert urls, "expected at least one URL"
    assert all(u.startswith("https://") for u in urls), urls
    assert any("GSE10072_family.soft.gz" in u for u in urls), urls


def test_extract_urls_accepts_https_scheme(clean_env: None) -> None:
    """NCBI now returns https:// URLs; the extractor must accept them."""
    import geomcp.geo_downloader as d

    xml = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE10nnn/GSE10072/"
    urls = d._extract_download_urls(xml)
    assert urls
    assert any("GSE10072_family.soft.gz" in u for u in urls)


def test_extract_urls_direct_soft_file_url(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    url = (
        "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE10nnn/GSE10072/"
        "soft/GSE10072_family.soft.gz"
    )
    assert d._extract_download_urls(url) == [url]


def test_extract_urls_gsm_builds_correct_soft_path(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    xml = "https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM254nnn/GSM254842/"
    urls = d._extract_download_urls(xml)
    assert any("GSM254842.soft.gz" in u for u in urls), urls
    assert all("GSM254842_family" not in u for u in urls), urls


def test_extract_urls_deduplicates(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    xml = (
        "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE10nnn/GSE10072/ "
        "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE10nnn/GSE10072/"
    )
    urls = d._extract_download_urls(xml)
    assert len(urls) == len(set(urls))


def test_extract_urls_empty_for_unrelated_xml(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    assert d._extract_download_urls("<foo>no urls here</foo>") == []


def test_backward_compat_aliases_exist(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    assert d._extract_ftp_links is d._extract_download_urls
    assert callable(d._load_config)


def test_configure_overrides_win(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    d.configure(email="test@example.org", max_concurrent_downloads=7)
    cfg = d._config()
    assert cfg["email"] == "test@example.org"
    assert cfg["max_concurrent_downloads"] == 7


def test_configure_ignores_none_values(clean_env: None) -> None:
    """argparse defaults of None must not clobber env / config.json."""
    import geomcp.geo_downloader as d

    d.configure(email="first@example.org")
    d.configure(email=None, max_concurrent_downloads=9)
    cfg = d._config()
    assert cfg["email"] == "first@example.org"
    assert cfg["max_concurrent_downloads"] == 9


def test_download_dir_defaults_to_xdg(clean_env: None) -> None:
    import geomcp.geo_downloader as d

    cfg = d._config()
    assert "geomcp" in cfg["download_dir"]
    assert "site-packages" not in cfg["download_dir"]


def test_legacy_config_location_is_still_read(
    clean_env: None, tmp_path, monkeypatch
) -> None:
    """Users with a pre-existing ~/.geo-mcp/config.json must keep working."""
    legacy_dir = tmp_path / ".geo-mcp"
    legacy_dir.mkdir()
    (legacy_dir / "config.json").write_text(
        '{"email": "legacy@example.org", "api_key": "legacy-key"}'
    )

    import geomcp.geo_downloader as d

    cfg = d._config()
    assert cfg["email"] == "legacy@example.org"
    assert cfg["api_key"] == "legacy-key"


def test_setup_environment_compat_shim(clean_env: None) -> None:
    """The deprecated symbol must still import and call without error."""
    from geomcp.main import setup_environment

    assert setup_environment() is None
