"""Boot-time diagnostics: the Ollama reachability probe used by friday.py."""
from __future__ import annotations

import config
import friday


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_ollama_base_appends_v1_when_missing(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    assert friday._ollama_base() == "http://127.0.0.1:11434/v1"


def test_ollama_base_keeps_existing_v1(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    assert friday._ollama_base() == "http://127.0.0.1:11434/v1"


def test_ollama_reachable_on_http_answer(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr("requests.get", lambda url, timeout=5: _Resp(200))
    reachable, detail = friday._ollama_reachable()
    assert reachable is True
    assert detail == "HTTP 200"


def test_ollama_reachable_false_on_5xx(monkeypatch):
    """A 504 from the gateway means the server behind it is not answering."""
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr("requests.get", lambda url, timeout=5: _Resp(504))
    reachable, detail = friday._ollama_reachable()
    assert reachable is False
    assert detail == "HTTP 504"


def test_ollama_reachable_false_on_connection_error(monkeypatch):
    import requests

    def boom(url, timeout=5):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr("requests.get", boom)
    reachable, detail = friday._ollama_reachable()
    assert reachable is False
    assert detail == "ConnectionError"
