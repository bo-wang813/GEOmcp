"""Shared fixtures for the GEOmcp test suite."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate each test from the real user environment.

    - Points $HOME, $XDG_CONFIG_HOME, $XDG_DATA_HOME at a tmp directory.
    - Clears GEOMCP_* env vars so configure() and config.json don't leak.
    - Drops geomcp.* from sys.modules so the re-import inside the test
      rebuilds module state (important: `_CONFIG_OVERRIDES` is module-level).
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    for var in (
        "CONFIG_PATH",
        "GEOMCP_EMAIL",
        "GEOMCP_API_KEY",
        "GEOMCP_BASE_URL",
        "GEOMCP_DOWNLOAD_DIR",
    ):
        monkeypatch.delenv(var, raising=False)

    for mod in [m for m in list(sys.modules) if m.startswith("geomcp")]:
        del sys.modules[mod]

    yield

    for mod in [m for m in list(sys.modules) if m.startswith("geomcp")]:
        del sys.modules[mod]
