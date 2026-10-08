"""Tests for the model fallback chain and message-format translation."""
from __future__ import annotations

import pytest

import config
from core.llm_engine import LLMEngine, LLMError


@pytest.fixture()
def keys(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key")


def test_chain_built_from_primary_and_fallbacks(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/llama-3.3-70b-versatile"])
    engine = LLMEngine()
    assert engine.get_model_status()["chain"] == [
        "gemini-2.5-flash",
        "groq/llama-3.3-70b-versatile",
    ]


def test_models_without_a_key_are_dropped(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/llama-3.3-70b-versatile"])
    assert LLMEngine().get_model_status()["chain"] == ["groq/llama-3.3-70b-versatile"]


def test_duplicates_collapse(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["gemini-2.5-flash", " gemini-2.5-flash "])
    assert LLMEngine().get_model_status()["chain"] == ["gemini-2.5-flash"]


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("  gemini-2.5-flash ", "gemini-2.5-flash"),
        ("groq/llama-3.3-70b-versatile - on_demand", "groq/llama-3.3-70b-versatile"),
        ("groq/llama3 – On Demand", "groq/llama3"),
    ],
)
def test_normalize_model_strips_ui_noise(raw, clean):
    assert LLMEngine._normalize_model(raw) == clean


def test_chat_without_available_providers_raises(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    monkeypatch.setattr(config, "OLLAMA_ENABLED", False)
    with pytest.raises(LLMError):
        list(LLMEngine().chat([{"role": "user", "content": "hi"}], []))


def test_chat_falls_back_to_the_next_model(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/llama-3.3-70b-versatile"])
    engine = LLMEngine()

    def dead_gemini(*a, **k):
        raise RuntimeError("503 unavailable")
        yield  # pragma: no cover

    def live_groq(*a, **k):
        yield ("text", "rescued")

    monkeypatch.setattr(engine, "_gemini_stream", dead_gemini)
    monkeypatch.setattr(engine, "_groq_stream", live_groq)
    assert list(engine.chat([{"role": "user", "content": "hi"}], [])) == [("text", "rescued")]


def test_chat_raises_when_every_model_fails(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/x"])
    engine = LLMEngine()

    def dead(*a, **k):
        raise RuntimeError("nope")
        yield  # pragma: no cover

    monkeypatch.setattr(engine, "_gemini_stream", dead)
    monkeypatch.setattr(engine, "_groq_stream", dead)
    with pytest.raises(LLMError, match="fallback chain failed"):
        list(engine.chat([{"role": "user", "content": "hi"}], []))


def test_set_primary_model_rebuilds_the_chain(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    engine = LLMEngine()
    engine.set_primary_model("gemini-2.5-pro")
    assert engine.get_model_status()["active_model"] == "gemini-2.5-pro"


def test_openai_translation_pairs_calls_with_responses(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "groq/llama")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    engine = LLMEngine("SYSTEM")
    msgs = [
        {"role": "user", "content": "read a.txt"},
        {"role": "model", "content": [{"function_call": {"name": "read_file", "args": {"p": "a"}}}]},
        {
            "role": "user",
            "content": [{"function_response": {"name": "read_file", "response": {"result": "DATA"}}}],
        },
    ]
    out = engine._to_openai_messages(msgs)
    assert out[0] == {"role": "system", "content": "SYSTEM"}
    assistant = next(m for m in out if m["role"] == "assistant")
    tool = next(m for m in out if m["role"] == "tool")
    assert tool["tool_call_id"] == assistant["tool_calls"][0]["id"]
    assert "DATA" in tool["content"]


def test_fallback_walks_the_chain_in_order(keys, monkeypatch):
    """Regression: the walk used to jump (0 → 1 → 3 → 2) because _model_index
    was mutated mid-walk — fallbacks must be tried in configured order."""
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-a")
    monkeypatch.setattr(
        config, "FALLBACK_MODELS", ["gemini-b", "groq/x", "groq/y"]
    )
    engine = LLMEngine()
    tried: list[str] = []

    def fail_gemini(messages, declarations, model_name):
        tried.append(model_name)
        raise RuntimeError("dead")
        yield  # pragma: no cover

    def fail_groq(messages, declarations, model_name):
        tried.append(model_name)
        raise RuntimeError("dead")
        yield  # pragma: no cover

    monkeypatch.setattr(engine, "_gemini_stream", fail_gemini)
    monkeypatch.setattr(engine, "_groq_stream", fail_groq)
    with pytest.raises(LLMError, match="fallback chain failed"):
        list(engine.chat([{"role": "user", "content": "hi"}], []))
    assert tried[:4] == ["gemini-a", "gemini-b", "groq/x", "groq/y"]


def test_successful_model_becomes_the_sticky_start(keys, monkeypatch):
    """After a successful fallback, the next chat() resumes at that model."""
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-a")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/x"])
    engine = LLMEngine()
    tried: list[str] = []

    def fail_gemini(messages, declarations, model_name):
        tried.append(model_name)
        raise RuntimeError("dead")
        yield  # pragma: no cover

    def live_groq(messages, declarations, model_name):
        tried.append(model_name)
        yield ("text", "ok")

    monkeypatch.setattr(engine, "_gemini_stream", fail_gemini)
    monkeypatch.setattr(engine, "_groq_stream", live_groq)
    assert list(engine.chat([{"role": "user", "content": "hi"}], [])) == [("text", "ok")]
    assert list(engine.chat([{"role": "user", "content": "again"}], [])) == [("text", "ok")]
    # second call resumes at groq/x — gemini-a is not retried first
    assert tried == ["gemini-a", "groq/x", "groq/x"]
