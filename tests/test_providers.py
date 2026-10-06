"""Tests for provider routing and the OpenAI-compatible SSE stream."""
from __future__ import annotations

import json

import pytest

import config
from core.llm_engine import LLMEngine, LLMError


@pytest.mark.parametrize(
    "model,provider",
    [
        ("gemini-3.8-flash", "gemini"),
        ("groq/llama-3.3-70b-versatile", "groq"),
        ("openrouter/meta-llama/llama-3.3-70b-instruct", "openrouter"),
        ("together/meta-llama/Llama-3.3-70B-Instruct-Turbo", "together"),
        ("GROQ/Llama3", "groq"),
    ],
)
def test_provider_detection(model, provider):
    assert LLMEngine._provider_for(model) == provider


def test_openrouter_model_joins_the_chain_when_keyed(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(config, "TOGETHER_API_KEY", None)
    monkeypatch.setattr(config, "PRIMARY_MODEL", "openrouter/some/model")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["together/other/model"])
    status = LLMEngine().get_model_status()
    assert status["chain"] == ["openrouter/some/model"]
    assert status["provider"] == "openrouter"


class FakeResponse:
    def __init__(self, lines, status_code=200, text=""):
        self._lines = lines
        self.status_code = status_code
        self.text = text

    def iter_lines(self, decode_unicode=False):
        yield from self._lines


def _sse(obj):
    return "data: " + json.dumps(obj)


def _delta(**delta):
    return _sse({"choices": [{"delta": delta}]})


@pytest.fixture()
def or_engine(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "openrouter/x/y")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    return LLMEngine("SYS")


def _patch_post(monkeypatch, response, captured=None):
    import requests

    def fake_post(url, **kwargs):
        if captured is not None:
            captured["url"] = url
            captured.update(kwargs)
        return response

    monkeypatch.setattr(requests, "post", fake_post)


def test_openai_compatible_stream_yields_text(or_engine, monkeypatch):
    lines = [_delta(content="Hello "), _delta(content="Boss"), "data: [DONE]"]
    _patch_post(monkeypatch, FakeResponse(lines))
    events = list(or_engine._openai_compatible_stream([], [], "openrouter/x/y", "openrouter"))
    assert events == [("text", "Hello "), ("text", "Boss")]


def test_openai_compatible_stream_assembles_tool_calls(or_engine, monkeypatch):
    lines = [
        _delta(tool_calls=[{"index": 0, "function": {"name": "read_", "arguments": '{"p":'}}]),
        _delta(tool_calls=[{"index": 0, "function": {"name": "file", "arguments": '"a.txt"}'}}]),
        "data: [DONE]",
    ]
    _patch_post(monkeypatch, FakeResponse(lines))
    events = list(or_engine._openai_compatible_stream([], [], "openrouter/x/y", "openrouter"))
    assert events == [("function_call", {"name": "read_file", "args": {"p": "a.txt"}})]


def test_malformed_tool_arguments_are_passed_through_raw(or_engine, monkeypatch):
    lines = [_delta(tool_calls=[{"index": 0, "function": {"name": "t", "arguments": "{oops"}}])]
    _patch_post(monkeypatch, FakeResponse(lines))
    events = list(or_engine._openai_compatible_stream([], [], "openrouter/x/y", "openrouter"))
    assert events[0][1]["args"] == {"raw": "{oops"}


def test_garbage_lines_are_ignored(or_engine, monkeypatch):
    lines = ["", ": keep-alive", "data: not json", _delta(content="ok"), "data: [DONE]"]
    _patch_post(monkeypatch, FakeResponse(lines))
    assert list(or_engine._openai_compatible_stream([], [], "openrouter/x/y", "openrouter")) == [
        ("text", "ok")
    ]


def test_http_error_becomes_llmerror(or_engine, monkeypatch):
    _patch_post(monkeypatch, FakeResponse([], status_code=402, text="no credits"))
    with pytest.raises(LLMError, match="402"):
        list(or_engine._openai_compatible_stream([], [], "openrouter/x/y", "openrouter"))


def test_request_carries_auth_model_and_tools(or_engine, monkeypatch):
    captured = {}
    _patch_post(monkeypatch, FakeResponse(["data: [DONE]"]), captured)
    decls = [{"name": "t", "description": "d", "parameters": {"type": "object", "properties": {}}}]
    list(or_engine._openai_compatible_stream([], decls, "openrouter/meta/llama-3", "openrouter"))
    assert captured["url"] == LLMEngine.OPENAI_COMPATIBLE_ENDPOINTS["openrouter"]
    assert captured["headers"]["Authorization"] == "Bearer or-key"
    assert captured["json"]["model"] == "meta/llama-3"
    assert captured["json"]["tools"][0]["function"]["name"] == "t"


def test_together_uses_its_own_endpoint(monkeypatch):
    monkeypatch.setattr(config, "TOGETHER_API_KEY", "tg-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "together/a/b")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    engine = LLMEngine()
    captured = {}
    _patch_post(monkeypatch, FakeResponse(["data: [DONE]"]), captured)
    list(engine._openai_compatible_stream([], [], "together/a/b", "together"))
    assert "together.xyz" in captured["url"]
