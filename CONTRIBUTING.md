# Contributing to GEOmcp

This repo follows the organization-wide contribution guidelines documented in
[`MCPmed/.github` → `CONTRIBUTING.md`](https://github.com/MCPmed/.github/blob/main/.github/CONTRIBUTING.md).
Read that first for the project philosophy, code style, commit message
conventions, and testing expectations.

Below are the GEOmcp-specific bits.

## Development setup

```bash
git clone https://github.com/MCPmed/GEOmcp.git
cd GEOmcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Running the checks locally

```bash
ruff check .
black --check .
pytest
```

GEOmcp's CI runs the same three checks via the reusable Python CI workflow in
`MCPmed/.github`; anything that is green locally should be green in GitHub
Actions.

## Configuring a local server for manual testing

The server needs an NCBI email address for E-utilities. Easiest path:

```bash
geo-mcp --init                             # interactive: writes an XDG config
# or
export GEOMCP_EMAIL="you@example.org"      # for a one-off run
geo-mcp --http                             # HTTP server on localhost:8001
```

Config resolution precedence (highest wins):

1. `configure()` runtime overrides (how the CLI wires in `--flags`)
2. `GEOMCP_*` environment variables
3. `config.json` at `$CONFIG_PATH`, `$XDG_CONFIG_HOME/geomcp/config.json`,
   or `~/.geo-mcp/config.json` (legacy fallback)
4. Built-in defaults

## Tests

New code that touches the download pipeline must come with a regression test.
The existing tests in `tests/test_downloader.py` are pure unit tests — they
do not hit the network. For tests that do need real NCBI fixtures, record
them with `vcrpy` rather than mocking out `aiohttp` by hand.

## Reporting a GEO-specific bug

If a specific GEO accession fails to download, please include:

- The exact accession (e.g. `GSE10072`, `GSM254842`).
- The `db_type` you requested.
- The full error message and the contents of `get_download_stats()`.
- Whether `curl https://ftp.ncbi.nlm.nih.gov/geo/series/GSE10nnn/GSE10072/`
  reaches NCBI from your network — rules out transient outages.
