"""Tests for provider routing and the OpenAI-compatible SSE stream."""
from __future__ import annotations

import json

import pytest

import config
from core.llm_engine import LLMEngine, LLMError


@pytest.mark.parametrize(
    "model,provider",
    [
        ("gemini-2.5-flash", "gemini"),
        ("ollama/llama3.2", "ollama"),
        ("ollama/deepseek-r1:7b", "ollama"),
        ("ollama/qwen2.5:7b", "ollama"),
        ("ollama", "ollama"),
        ("groq/llama-3.3-70b-versatile", "groq"),
        ("openrouter/meta-llama/llama-3.3-70b-instruct", "openrouter"),
        ("together/meta-llama/Llama-3.3-70B-Instruct-Turbo", "together"),
        ("GROQ/Llama3", "groq"),
    ],
)
def test_provider_detection(model, provider):
    assert LLMEngine._provider_for(model) == provider


def test_friday_model_takes_precedence_over_gemini_model(monkeypatch):
    monkeypatch.setenv("FRIDAY_MODEL", "ollama/deepseek-r1:7b")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    assert config._get_preferred("FRIDAY_MODEL", "GEMINI_MODEL", "default") == (
        "ollama/deepseek-r1:7b"
    )


def test_gemini_model_remains_a_legacy_fallback(monkeypatch):
    monkeypatch.delenv("FRIDAY_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    assert config._get_preferred("FRIDAY_MODEL", "GEMINI_MODEL", "default") == (
        "gemini-2.5-flash"
    )


def test_present_empty_friday_model_still_takes_precedence(monkeypatch):
    monkeypatch.setenv("FRIDAY_MODEL", "")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    assert config._get_preferred("FRIDAY_MODEL", "GEMINI_MODEL", "default") == ""


def test_friday_fallbacks_take_precedence_even_when_empty(monkeypatch):
    monkeypatch.setenv("FRIDAY_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "groq/llama")
    assert config._get_preferred_csv(
        "FRIDAY_FALLBACK_MODELS", "GEMINI_FALLBACK_MODELS", "default/model"
    ) == []


def test_both_empty_fallback_variables_leave_ollama_as_the_only_model(monkeypatch):
    monkeypatch.setenv("FRIDAY_MODEL", "ollama/llama3.2")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("FRIDAY_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    monkeypatch.setattr(
        config,
        "PRIMARY_MODEL",
        config._get_preferred("FRIDAY_MODEL", "GEMINI_MODEL", "gemini-2.5-flash"),
    )
    monkeypatch.setattr(
        config,
        "FALLBACK_MODELS",
        config._get_preferred_csv(
            "FRIDAY_FALLBACK_MODELS",
            "GEMINI_FALLBACK_MODELS",
            "gemini-lite,groq/llama",
        ),
    )
    monkeypatch.setattr(config, "OLLAMA_ENABLED", True)
    for name in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "TOGETHER_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.setattr(config, name, None)

    assert LLMEngine().get_model_status()["chain"] == ["ollama/llama3.2"]


def test_gemini_fallbacks_remain_a_legacy_fallback(monkeypatch):
    monkeypatch.delenv("FRIDAY_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "groq/llama")
    assert config._get_preferred_csv(
        "FRIDAY_FALLBACK_MODELS", "GEMINI_FALLBACK_MODELS", "default/model"
    ) == ["groq/llama"]


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


def test_ollama_joins_the_chain_without_any_external_api_key(monkeypatch):
    for name in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "TOGETHER_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.setattr(config, name, None)
    monkeypatch.setattr(config, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.2")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "ollama/llama3.2")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])

    status = LLMEngine().get_model_status()

    assert status["chain"] == ["ollama/llama3.2"]
    assert status["provider"] == "ollama"


def test_disabled_ollama_is_skipped(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_ENABLED", False)
    monkeypatch.setattr(config, "PRIMARY_MODEL", "ollama/llama3.2")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    assert LLMEngine().get_model_status()["chain"] == []


def test_ollama_shorthand_uses_the_configured_model(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen2.5:7b")
    assert LLMEngine._normalize_model("ollama") == "ollama/qwen2.5:7b"


def test_empty_fallback_environment_setting_disables_fallbacks(monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    assert config._get_csv("GEMINI_FALLBACK_MODELS", "gemini-lite,groq/llama") == []


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


@pytest.fixture()
def ollama_engine(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://ollama.local:11434/v1")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.2")
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    monkeypatch.setattr(config, "PRIMARY_MODEL", "ollama/llama3.2")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    return LLMEngine("SYS")


def test_ollama_compatible_stream_preserves_streaming_and_tool_calls(
    ollama_engine, monkeypatch
):
    lines = [
        _delta(content="Hello from local Ollama").encode("utf-8"),
        _delta(
            tool_calls=[
                {
                    "index": 0,
                    "function": {"name": "get_current_time", "arguments": '{"timezone":"UTC"}'},
                }
            ]
        ),
        "data: [DONE]",
    ]
    captured = {}
    _patch_post(monkeypatch, FakeResponse(lines), captured)
    declarations = [
        {
            "name": "get_current_time",
            "description": "Get the current time",
            "parameters": {"type": "object", "properties": {"timezone": {"type": "string"}}},
        }
    ]

    events = list(
        ollama_engine._openai_compatible_stream(
            [{"role": "user", "content": "hi"}],
            declarations,
            "ollama/llama3.2",
            "ollama",
        )
    )

    assert captured["url"] == "http://ollama.local:11434/v1/chat/completions"
    assert captured["json"]["model"] == "llama3.2"
    assert captured["json"]["stream"] is True
    assert captured["json"]["tools"][0]["function"]["name"] == "get_current_time"
    assert "Authorization" not in captured["headers"]
    assert events == [
        ("text", "Hello from local Ollama"),
        ("function_call", {"name": "get_current_time", "args": {"timezone": "UTC"}}),
    ]


def test_ollama_endpoint_adds_v1_for_a_server_root(ollama_engine, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://ollama.local:11434")
    assert ollama_engine._endpoint_for("ollama") == (
        "http://ollama.local:11434/v1/chat/completions"
    )


@pytest.mark.parametrize(
    "model_name,model_id",
    [
        ("ollama/llama3.2", "llama3.2"),
        ("ollama/deepseek-r1:7b", "deepseek-r1:7b"),
        ("ollama/qwen2.5:7b", "qwen2.5:7b"),
    ],
)
def test_ollama_extracts_model_tag_and_sends_no_auth(
    ollama_engine, monkeypatch, model_name, model_id
):
    captured = {}
    _patch_post(monkeypatch, FakeResponse(["data: [DONE]"]), captured)

    list(ollama_engine._openai_compatible_stream([], [], model_name, "ollama"))

    assert captured["url"] == "http://ollama.local:11434/v1/chat/completions"
    assert captured["json"]["model"] == model_id
    assert "Authorization" not in captured["headers"]


def test_ollama_streams_text(ollama_engine, monkeypatch):
    lines = [_delta(content="local response").encode("utf-8"), "data: [DONE]"]
    _patch_post(monkeypatch, FakeResponse(lines))
    assert list(
        ollama_engine._openai_compatible_stream(
            [{"role": "user", "content": "hi"}], [], "ollama/llama3.2", "ollama"
        )
    ) == [("text", "local response")]


def test_ollama_connection_error_suggests_server_command_and_url(ollama_engine, monkeypatch):
    import requests

    def fail_post(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", fail_post)
    with pytest.raises(LLMError) as exc_info:
        list(ollama_engine._openai_compatible_stream([], [], "ollama/llama3.2", "ollama"))
    message = str(exc_info.value)
    assert "ollama serve" in message
    assert config.OLLAMA_BASE_URL in message


def test_ollama_missing_model_suggests_list_and_pull(ollama_engine, monkeypatch):
    _patch_post(
        monkeypatch,
        FakeResponse([], status_code=404, text='model "deepseek-r1:7b" not found'),
    )
    with pytest.raises(LLMError) as exc_info:
        list(
            ollama_engine._openai_compatible_stream(
                [], [], "ollama/deepseek-r1:7b", "ollama"
            )
        )
    message = str(exc_info.value)
    assert "ollama list" in message
    assert "ollama pull deepseek-r1:7b" in message
    assert config.OLLAMA_BASE_URL in message


def test_ollama_413_is_size_error_not_rate_limit(ollama_engine, monkeypatch):
    _patch_post(
        monkeypatch,
        FakeResponse(
            [],
            status_code=413,
            text='{"error":{"message":"request too large","code":"rate_limit_exceeded"}}',
        ),
    )
    with pytest.raises(LLMError) as exc_info:
        list(ollama_engine._openai_compatible_stream([], [], "ollama/llama3.2", "ollama"))
    message = str(exc_info.value).lower()
    assert "http 413" in message
    assert "oversized request" in message
    assert "not an ordinary rate limit" in message


def test_ollama_413_does_not_retry_same_request(ollama_engine, monkeypatch):
    import requests

    calls = []

    def reject_as_too_large(*_args, **_kwargs):
        calls.append(1)
        return FakeResponse([], status_code=413, text="request too large")

    monkeypatch.setattr(requests, "post", reject_as_too_large)
    with pytest.raises(LLMError, match="not retrying it unchanged"):
        list(ollama_engine.chat([{"role": "user", "content": "large"}], []))
    assert len(calls) == 1


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
