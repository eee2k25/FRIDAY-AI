"""Tests for FRIDAY_MODEL / FRIDAY_FALLBACK_MODELS precedence and provider errors.

Covers the local-Ollama-first configuration contract:

* ``FRIDAY_MODEL`` overrides the legacy ``GEMINI_MODEL`` name.
* ``FRIDAY_FALLBACK_MODELS`` overrides ``GEMINI_FALLBACK_MODELS``.
* An explicitly empty ``FRIDAY_FALLBACK_MODELS`` means *no* fallback providers
  (that is different from leaving the variable unset, which falls through).
* A keyless ``ollama/<model>`` stays in the provider chain.
"""
from __future__ import annotations

import importlib
import json

import pytest

import config
from core.llm_engine import LLMEngine, LLMError

DEFAULT_FALLBACKS = ["gemini-2.5-flash-lite", "groq/llama-3.3-70b-versatile"]


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    """Re-import config after every test so reloaded globals never leak.

    ``importlib.reload`` rewrites the module globals that every other test
    monkeypatches, so undo it here — monkeypatch restores os.environ first,
    which makes the reload reproduce the pre-test state.
    """
    yield
    importlib.reload(config)


@pytest.fixture()
def clean_env(monkeypatch):
    """Strip every model/credential variable so only what a test sets applies."""
    for name in (
        "FRIDAY_MODEL",
        "GEMINI_MODEL",
        "FRIDAY_FALLBACK_MODELS",
        "GEMINI_FALLBACK_MODELS",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "TOGETHER_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------- FRIDAY_MODEL ---
def test_friday_model_overrides_gemini_model(clean_env, monkeypatch):
    monkeypatch.setenv("FRIDAY_MODEL", "ollama/llama3.2")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    importlib.reload(config)
    assert config.PRIMARY_MODEL == "ollama/llama3.2"


def test_gemini_model_is_used_when_friday_model_absent(clean_env, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    importlib.reload(config)
    assert config.PRIMARY_MODEL == "gemini-2.0-flash"


def test_friday_model_wins_over_an_empty_gemini_model(clean_env, monkeypatch):
    """An empty GEMINI_MODEL must not shadow FRIDAY_MODEL."""
    monkeypatch.setenv("FRIDAY_MODEL", "ollama/qwen2.5:7b")
    monkeypatch.setenv("GEMINI_MODEL", "")
    importlib.reload(config)
    assert config.PRIMARY_MODEL == "ollama/qwen2.5:7b"


def test_primary_model_falls_back_to_a_sane_default(clean_env):
    importlib.reload(config)
    assert config.PRIMARY_MODEL == "gemini-2.5-flash"


# ---------------------------------------------- FRIDAY_FALLBACK_MODELS ---
def test_friday_fallbacks_override_gemini_fallbacks(clean_env, monkeypatch):
    monkeypatch.setenv("FRIDAY_FALLBACK_MODELS", "groq/llama-3.3-70b-versatile")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "together/should/be/ignored")
    importlib.reload(config)
    assert config.FALLBACK_MODELS == ["groq/llama-3.3-70b-versatile"]


def test_gemini_fallbacks_used_when_friday_fallbacks_absent(clean_env, monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "groq/llama-3.3-70b-versatile")
    importlib.reload(config)
    assert config.FALLBACK_MODELS == ["groq/llama-3.3-70b-versatile"]


def test_explicitly_empty_friday_fallbacks_disables_the_chain(clean_env, monkeypatch):
    """`FRIDAY_FALLBACK_MODELS=` is a decision, not an omission."""
    monkeypatch.setenv("FRIDAY_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "groq/llama-3.3-70b-versatile")
    importlib.reload(config)
    assert config.FALLBACK_MODELS == []


def test_unset_friday_fallbacks_falls_through_to_the_default(clean_env):
    importlib.reload(config)
    assert config.FALLBACK_MODELS == DEFAULT_FALLBACKS


def test_csv_helper_trims_and_drops_blanks(clean_env, monkeypatch):
    monkeypatch.setenv("FRIDAY_FALLBACK_MODELS", " a/b , ,c/d ,")
    assert config._get_csv_first("FRIDAY_FALLBACK_MODELS", "x/y") == ["a/b", "c/d"]


def test_csv_helper_first_set_variable_wins(clean_env, monkeypatch):
    monkeypatch.setenv("FRIDAY_FALLBACK_MODELS", "a/b")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "c/d")
    assert config._get_csv_first("FRIDAY_FALLBACK_MODELS", "GEMINI_FALLBACK_MODELS", "z/z") == [
        "a/b"
    ]


# --------------------------------------- end-to-end keyless local setup ---
def test_ollama_only_setup_builds_a_single_model_chain(clean_env, monkeypatch):
    """The documented local config: FRIDAY_MODEL=ollama/llama3.2, no fallbacks."""
    monkeypatch.setenv("FRIDAY_MODEL", "ollama/llama3.2")
    monkeypatch.setenv("FRIDAY_FALLBACK_MODELS", "")
    monkeypatch.setenv("OLLAMA_ENABLED", "True")
    importlib.reload(config)

    status = LLMEngine().get_model_status()

    assert status["chain"] == ["ollama/llama3.2"]
    assert status["provider"] == "ollama"


# ------------------------------------------------------- tagged models ---
@pytest.mark.parametrize(
    "model,expected",
    [
        ("ollama/llama3.2", "llama3.2"),
        ("ollama/deepseek-r1:7b", "deepseek-r1:7b"),
        ("ollama/qwen2.5:7b", "qwen2.5:7b"),
        ("ollama/llama3.1:70b-instruct-q4_K_M", "llama3.1:70b-instruct-q4_K_M"),
    ],
)
def test_tagged_ollama_models_keep_their_tag(model, expected):
    """`model_name.split('/', 1)[1]` must not truncate a `:tag` suffix."""
    assert model.split("/", 1)[1] == expected
    assert LLMEngine._provider_for(model) == "ollama"


# --------------------------------------------------------- DeepSeek ---
def test_deepseek_is_a_supported_optional_provider():
    assert LLMEngine._provider_for("deepseek/deepseek-chat") == "deepseek"
    assert "deepseek" in LLMEngine.OPENAI_COMPATIBLE_ENDPOINTS
    assert LLMEngine._requires_api_key("deepseek") is True


def test_deepseek_stays_out_of_the_chain_without_a_key(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", None)
    monkeypatch.setattr(config, "PRIMARY_MODEL", "deepseek/deepseek-chat")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    assert LLMEngine().get_model_status()["chain"] == []


def test_deepseek_joins_the_chain_when_keyed(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "deepseek/deepseek-chat")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])

    status = LLMEngine().get_model_status()

    assert status["chain"] == ["deepseek/deepseek-chat"]
    assert LLMEngine._key_for("deepseek") == "ds-key"


def test_deepseek_uses_its_own_endpoint(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "deepseek/deepseek-chat")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    engine = LLMEngine()

    captured = {}
    _patch_post(monkeypatch, _FakeResponse(["data: [DONE]"]), captured)
    list(engine._openai_compatible_stream([], [], "deepseek/deepseek-chat", "deepseek"))

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["json"]["model"] == "deepseek-chat"
    assert captured["headers"]["Authorization"] == "Bearer ds-key"


# --------------------------------------------- Ollama actionable errors ---
class _FakeResponse:
    def __init__(self, lines, status_code=200, text=""):
        self._lines = lines
        self.status_code = status_code
        self.text = text

    def iter_lines(self, decode_unicode=False):
        yield from self._lines


def _patch_post(monkeypatch, response, captured=None):
    import requests

    def fake_post(url, **kwargs):
        if captured is not None:
            captured["url"] = url
            captured.update(kwargs)
        return response

    monkeypatch.setattr(requests, "post", fake_post)


@pytest.fixture()
def ollama(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.2")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "ollama/llama3.2")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    return LLMEngine("SYS")


def _stream(engine):
    return list(engine._openai_compatible_stream([], [], "ollama/llama3.2", "ollama"))


def test_ollama_connection_error_mentions_serve_and_base_url(ollama, monkeypatch):
    import requests

    def fail_post(*_a, **_k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", fail_post)
    with pytest.raises(LLMError) as exc:
        _stream(ollama)
    msg = str(exc.value)
    assert "ollama serve" in msg
    assert config.OLLAMA_BASE_URL in msg


def test_missing_model_error_mentions_ollama_list_and_pull(ollama, monkeypatch):
    _patch_post(monkeypatch, _FakeResponse([], status_code=404, text="model not found"))
    with pytest.raises(LLMError) as exc:
        _stream(ollama)
    msg = str(exc.value)
    assert "ollama list" in msg
    assert "ollama pull llama3.2" in msg


def test_oversized_request_is_413_not_a_rate_limit(ollama, monkeypatch):
    _patch_post(monkeypatch, _FakeResponse([], status_code=413, text="too big"))
    with pytest.raises(LLMError) as exc:
        _stream(ollama)
    msg = str(exc.value)
    assert "413" in msg
    assert "too large" in msg.lower()
    # Never phrased like a transient rate limit — that would be retried unchanged.
    for word in ("rate limit", "rate_limit", "429", "quota"):
        assert word not in msg.lower()


def test_oversized_413_routes_to_the_context_diet_not_a_retry(ollama, monkeypatch):
    """The 413 message must trip the agent loop's oversized branch."""
    from core.agent_loop import AgentLoop

    _patch_post(monkeypatch, _FakeResponse([], status_code=413, text="too big"))
    with pytest.raises(LLMError) as exc:
        _stream(ollama)
    err = str(exc.value).lower()

    assert any(k in err for k in AgentLoop._OVERSIZED_SIGNALS)
    assert not any(k in err for k in AgentLoop._RETRY_SIGNALS)


def test_generic_deepseek_413_is_also_labelled_oversized(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "deepseek/deepseek-chat")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    _patch_post(monkeypatch, _FakeResponse([], status_code=413, text="too big"))

    with pytest.raises(LLMError) as exc:
        list(
            LLMEngine()._openai_compatible_stream([], [], "deepseek/deepseek-chat", "deepseek")
        )
    assert "413" in str(exc.value)


# --------------------------------------------- Ollama request shape ---
def test_ollama_request_shape(ollama, monkeypatch):
    """Base URL + /chat/completions, no Authorization, tagged model preserved."""
    captured = {}
    _patch_post(monkeypatch, _FakeResponse(["data: [DONE]"]), captured)
    list(ollama._openai_compatible_stream([], [], "ollama/deepseek-r1:7b", "ollama"))

    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["json"]["model"] == "deepseek-r1:7b"
    assert captured["json"]["stream"] is True
    assert "Authorization" not in captured["headers"]


def test_ollama_streams_text_and_tool_calls(ollama, monkeypatch):
    def sse(obj):
        return "data: " + json.dumps(obj)

    lines = [
        sse({"choices": [{"delta": {"content": "Hello "}}]}),
        sse({"choices": [{"delta": {"content": "Boss"}}]}),
        sse(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "read_", "arguments": '{"p":'}}
                            ]
                        }
                    }
                ]
            }
        ),
        sse(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "file", "arguments": '"a.txt"}'}}
                            ]
                        }
                    }
                ]
            }
        ),
        "data: [DONE]",
    ]
    _patch_post(monkeypatch, _FakeResponse(lines))

    assert _stream(ollama) == [
        ("text", "Hello "),
        ("text", "Boss"),
        ("function_call", {"name": "read_file", "args": {"p": "a.txt"}}),
    ]
