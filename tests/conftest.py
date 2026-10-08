"""Shared pytest fixtures.

Every test runs against a throwaway memory DB and log dir so the developer's
real memory/friday_memory.db is never touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_memory(tmp_path, monkeypatch):
    """A FridayMemory backed by a temporary SQLite file."""
    import config
    from core.memory import FridayMemory

    db = tmp_path / "test_memory.db"
    monkeypatch.setattr(config, "MEMORY_DB_PATH", db, raising=False)
    mem = FridayMemory(db)
    yield mem
    mem._conn.close()


@pytest.fixture()
def registry():
    from core.tool_registry import ToolRegistry

    return ToolRegistry()


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Fail loudly on any real HTTP request made by a test.

    The suite is offline by design (see README). Ollama is in the default
    fallback chain, so an engine built with default config would otherwise
    call the real endpoint from CI. Tests that need a response patch
    `requests` themselves; anything else gets a ConnectionError, which the
    engine treats as an unreachable provider.
    """
    import requests

    def _blocked(self, request, *args, **kwargs):
        raise requests.exceptions.ConnectionError(
            f"network access is disabled in tests: {request.method} {request.url}"
        )

    monkeypatch.setattr(requests.Session, "send", _blocked)
