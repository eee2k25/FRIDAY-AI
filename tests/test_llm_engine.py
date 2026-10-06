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
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/openai/gpt-oss-120b"])
    engine = LLMEngine()
    assert engine.get_model_status()["chain"] == [
        "gemini-3.8-flash",
        "groq/openai/gpt-oss-120b",
    ]


def test_models_without_a_key_are_dropped(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/openai/gpt-oss-120b"])
    assert LLMEngine().get_model_status()["chain"] == ["groq/openai/gpt-oss-120b"]


def test_duplicates_collapse(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["gemini-3.8-flash", " gemini-3.8-flash "])
    assert LLMEngine().get_model_status()["chain"] == ["gemini-3.8-flash"]


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("  gemini-3.8-flash ", "gemini-3.8-flash"),
        ("groq/openai/gpt-oss-120b - on_demand", "groq/openai/gpt-oss-120b"),
        ("groq/llama3 – On Demand", "groq/llama3"),
    ],
)
def test_normalize_model_strips_ui_noise(raw, clean):
    assert LLMEngine._normalize_model(raw) == clean


def test_chat_without_keys_raises(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    with pytest.raises(LLMError):
        list(LLMEngine().chat([{"role": "user", "content": "hi"}], []))


def test_chat_falls_back_to_the_next_model(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/openai/gpt-oss-120b"])
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
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-3.8-flash")
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
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    engine = LLMEngine()
    engine.set_primary_model("gemini-3.8-pro")
    assert engine.get_model_status()["active_model"] == "gemini-3.8-pro"


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


DELISTED_404 = (
    "404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model "
    "models/gemini-9.9-flash is no longer available to new users. Please update "
    "your code to use models/gemini-3.8-flash for the latest features.', "
    "'status': 'NOT_FOUND'}}"
)


def test_delisted_model_404_is_remapped_and_retried(keys, monkeypatch):
    monkeypatch.setattr(config, "RETIRED_MODELS", dict(config.RETIRED_MODELS))
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-9.9-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    engine = LLMEngine()
    seen: list[str] = []

    def gemini(messages, declarations, model_name):
        seen.append(model_name)
        if model_name == "gemini-9.9-flash":
            raise RuntimeError(DELISTED_404)
        yield ("text", "ok")

    monkeypatch.setattr(engine, "_gemini_stream", gemini)
    assert list(engine.chat([{"role": "user", "content": "hi"}], [])) == [("text", "ok")]
    assert seen == ["gemini-9.9-flash", "gemini-3.8-flash"]
    assert engine.get_model_status()["chain"] == ["gemini-3.8-flash"]
    assert config.PRIMARY_MODEL == "gemini-3.8-flash"


def test_remap_only_applies_to_delisting_errors(keys, monkeypatch):
    assert LLMEngine._suggested_replacement(RuntimeError("503 busy"), "gemini-9.9-flash") is None
    assert (
        LLMEngine._suggested_replacement(RuntimeError(DELISTED_404), "gemini-9.9-flash")
        == "gemini-3.8-flash"
    )


def test_retired_names_are_rewritten_before_any_api_call(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["gemini-2.5-flash-lite"])
    assert LLMEngine().get_model_status()["chain"] == [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
    ]


def test_model_command_with_a_retired_name_is_corrected(keys, monkeypatch):
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    engine = LLMEngine()
    engine.set_primary_model("gemini-2.5-pro")
    assert engine.get_model_status()["active_model"] == "gemini-3.8-flash"


def test_no_shipped_default_points_at_a_retired_model():
    defaults = [config.DEFAULT_PRIMARY_MODEL, *config.DEFAULT_FALLBACK_MODELS.split(",")]
    assert not [m for m in defaults if m.strip().lower() in config.RETIRED_MODELS]
