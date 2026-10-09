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


def test_served_models_reads_both_endpoint_shapes(monkeypatch):
    """Ollama's native /api/tags list and the OpenAI-compatible /v1/models list
    use different keys, and FRIDAY's config may point at either."""
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")

    class R:
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    seen = []

    def fake_get(url, timeout=None):
        seen.append(url)
        return R({"data": [{"id": "llama3.2:latest"}]})

    monkeypatch.setattr("requests.get", fake_get)
    assert friday._ollama_served_models() == (["llama3.2:latest"], "")
    assert seen == ["http://127.0.0.1:11434/v1/models"]

    monkeypatch.setattr(
        "requests.get", lambda url, timeout=None: R({"models": [{"name": "qwen2.5:3b"}]})
    )
    assert friday._ollama_served_models() == (["qwen2.5:3b"], "")

    monkeypatch.setattr(
        "requests.get",
        lambda url, timeout=None: (_ for _ in ()).throw(ConnectionError()),
    )
    assert friday._ollama_served_models() == ([], "ConnectionError")


def test_served_models_reports_http_errors_without_raising(monkeypatch):
    """A probe that raises would take the doctor down with it."""
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")

    class R:
        status_code = 401

        def json(self):
            return {}

    monkeypatch.setattr("requests.get", lambda url, timeout=None: R())
    assert friday._ollama_served_models() == ([], "HTTP 401")
