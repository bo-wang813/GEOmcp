# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Regression test suite covering the import-time crash, URL scheme
  handling for both `ftp://` and `https://`, `configure()` override
  precedence, XDG defaults, and legacy config fallback.
- `configure(**overrides)` runtime config API; CLI flags (`--email`,
  `--api-key`, `--download-dir`, `--max-*`) now actually apply through
  this path.
- `GEOMCP_EMAIL`, `GEOMCP_API_KEY`, `GEOMCP_BASE_URL`, and
  `GEOMCP_DOWNLOAD_DIR` environment variables as a config layer between
  `config.json` and runtime overrides.
- `.pre-commit-config.yaml`, `CHANGELOG.md`, `CONTRIBUTING.md`.
- `.github/workflows/ci.yml` that delegates to the organization-wide
  reusable Python CI workflow.

### Changed

- **Breaking (for the uncommon case):** default `download_dir` is now
  `$XDG_DATA_HOME/geomcp/downloads` instead of `./downloads` resolved
  relative to the installed package directory. Users with an existing
  `~/.geo-mcp/config.json` are unaffected — that location is still
  honored as a fallback, and an existing legacy file is also where
  `geo-mcp --init` now writes to avoid orphaning existing installs.
- `geo_downloader` config is now loaded lazily with four precedence
  layers (runtime overrides → env vars → `config.json` → defaults).
  Config is no longer read at module import time.
- E-utilities calls (`esearch`, `efetch`) migrated from blocking
  `requests` to `aiohttp` to stop stalling the stdio event loop.
- License aligned: `pyproject.toml` and `README.md` badge now match
  the BSD-3-Clause `LICENSE` file (they previously said MIT).

### Fixed

- **Downloads broken for every valid accession since mid-2024.** NCBI
  retired its anonymous FTP endpoint and E-utilities now returns
  `https://ftp.ncbi.nlm.nih.gov/...` URLs. The old regex only matched
  `ftp://` and silently dropped every response, producing spurious
  "no downloadable SOFT file exposed" errors. URL extraction now
  accepts both schemes and normalises to `https://`.
- **Package could not be imported without a pre-existing `config.json`.**
  `geo_downloader` ran `_load_config()` at module scope and called
  `sys.exit(1)` if `email` was missing, breaking pytest, mypy, and any
  environment without a config file.
- **First-run bootstrap was broken.** `main.setup_environment()`
  tried to copy a `config_template.json` that does not exist in the
  package, then `sys.exit(1)`ed.
- `asyncio.Semaphore` for concurrent downloads no longer lives at
  module scope; it is now created per event loop, preventing
  "attached to a different loop" errors under MCP stdio.
- `main.py` no longer `os.chdir()`s the process into the install
  directory or prepends a fictional `.venv/bin` to `PATH`.
- Pre-existing ruff errors (`F401`, `F841`, `E401`) and black
  formatting inconsistencies across the package were cleaned up so CI
  is green on the first run.

### Removed

- Duplicate release workflow (`python-publish.yml` overlapped with
  `pypi-publish.yml`; both fired on `release: published` and would
  double-upload).
- Broken `test.yml` workflow that invoked pytest against a
  non-existent `geo_mcp_server/test/` directory.
- Stale `.github/WORKFLOWS.md` that documented a workflow layout the
  repo never actually had.

## [0.1.1] - 2025

Initial tagged release on PyPI.
