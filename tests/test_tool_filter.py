"""Tests for per-turn tool filtering, oversized-request recovery, and
SDK-availability handling in the model chain."""
from __future__ import annotations

import builtins

import pytest

import config
from core.agent_loop import AgentLoop
from core.llm_engine import LLMEngine, LLMError
from core.tool_registry import ToolRegistry


def _decl(name, desc):
    return {
        "name": name,
        "description": desc,
        "parameters": {"type": "object", "properties": {}},
    }


@pytest.fixture()
def big_registry():
    reg = ToolRegistry()
    reg.register_tool("read_file", lambda path: path, _decl("read_file", "Read a text file from disk"))
    reg.register_tool("write_file", lambda path, content: "ok", _decl("write_file", "Write a text file to disk"))
    reg.register_tool("web_search", lambda q: q, _decl("web_search", "Search the web for information"))
    reg.register_tool("create_excel", lambda path: "ok", _decl("create_excel", "Create an Excel spreadsheet workbook"))
    reg.register_tool("add_excel_chart", lambda path: "ok", _decl("add_excel_chart", "Add a chart to an Excel sheet"))
    reg.register_tool("create_word_doc", lambda path: "ok", _decl("create_word_doc", "Create a Word document"))
    reg.register_tool("send_email", lambda to: "ok", _decl("send_email", "Send an email message"))
    return reg


# ------------------------------------------------------- registry filter ---
def test_core_tools_always_included(big_registry):
    sel = {d["name"] for d in big_registry.select_declarations("zzz qqq unmatched", cap=40)}
    assert {"read_file", "write_file", "web_search"} <= sel


def test_relevant_tools_ranked_in(big_registry):
    sel = {d["name"] for d in big_registry.select_declarations("make an excel spreadsheet with a chart", cap=40)}
    assert "create_excel" in sel
    assert "add_excel_chart" in sel


def test_unrelated_tools_dropped(big_registry):
    sel = {d["name"] for d in big_registry.select_declarations("make an excel spreadsheet", cap=40)}
    assert "send_email" not in sel


def test_cap_zero_disables_filtering(big_registry):
    assert len(big_registry.select_declarations("anything", cap=0)) == len(
        big_registry.get_declarations()
    )


def test_cap_is_respected(big_registry):
    sel = big_registry.select_declarations("excel chart email word file search write", cap=3)
    assert len(sel) <= 3


def test_extra_names_always_included(big_registry):
    sel = {d["name"] for d in big_registry.select_declarations("unrelated query", cap=40, extra_names=["send_email"])}
    assert "send_email" in sel


def test_pool_limits_selection(big_registry):
    pool = [d for d in big_registry.get_declarations() if d["name"] in ("send_email", "create_word_doc")]
    sel = {d["name"] for d in big_registry.select_declarations("read a file", cap=40, pool=pool)}
    assert sel <= {"send_email", "create_word_doc"}


def test_compact_tool_list_is_shorter_and_keeps_names(big_registry):
    # long descriptions get truncated to one short line in compact mode
    big_registry.register_tool(
        "noisy_tool",
        lambda: "ok",
        _decl("noisy_tool", "A very long description. " * 20 + "Trailing detail that must be cut."),
    )
    full = big_registry.list_tools()
    compact = big_registry.list_tools(compact=True)
    assert len(compact) < len(full)
    assert all(name in compact for name in ("read_file", "send_email", "noisy_tool"))
    noisy_line = next(l for l in compact.splitlines() if l.startswith("- noisy_tool:"))
    assert len(noisy_line) < 100  # one short line, not the full description


# --------------------------------------------------------- loop integration ---
class _Engine:
    """Fake engine that records the declarations it was called with."""

    def __init__(self, behavior):
        self.behavior = behavior
        self.declarations_seen = []
        self.system_prompt = ""

    def set_system_prompt(self, prompt):
        self.system_prompt = prompt

    def chat(self, messages, declarations):
        self.declarations_seen.append(declarations)
        yield from self.behavior(messages, declarations)

    def get_model_status(self):
        return {"active_model": "fake", "provider": "fake", "chain": ["fake"], "calls": {}, "last_error": None}


def test_loop_sends_filtered_tools(tmp_memory, big_registry, monkeypatch):
    monkeypatch.setattr(config, "TOOL_FILTER_ENABLED", True)
    monkeypatch.setattr(config, "MAX_TOOLS_PER_CALL", 40)
    engine = _Engine(lambda m, d: iter([("text", "hi Boss")]))
    agent = AgentLoop(engine, big_registry, tmp_memory, persona=lambda **kw: "SYS")
    agent.run("hello there", "s-filter")
    sent = engine.declarations_seen[0]
    assert 0 < len(sent) < len(big_registry.get_declarations())


def test_loop_filter_disabled_sends_everything(tmp_memory, big_registry, monkeypatch):
    monkeypatch.setattr(config, "TOOL_FILTER_ENABLED", False)
    engine = _Engine(lambda m, d: iter([("text", "hi Boss")]))
    agent = AgentLoop(engine, big_registry, tmp_memory, persona=lambda **kw: "SYS")
    agent.run("hello there", "s-nofilter")
    assert len(engine.declarations_seen[0]) == len(big_registry.get_declarations())


def test_loop_keeps_session_tools_declared(tmp_memory, big_registry, monkeypatch):
    """A tool used earlier in the session stays available on later turns."""
    monkeypatch.setattr(config, "TOOL_FILTER_ENABLED", True)
    monkeypatch.setattr(config, "MAX_TOOLS_PER_CALL", 40)
    scripts = iter([
        [("function_call", {"name": "send_email", "args": {"to": "x"}})],
        [("text", "mailed")],
    ])
    engine = _Engine(lambda m, d: next(scripts))
    agent = AgentLoop(engine, big_registry, tmp_memory, persona=lambda **kw: "SYS")
    agent.run("send an email and then say something unrelated about penguins", "s-tools")
    assert "send_email" in {d["name"] for d in engine.declarations_seen[1]}


# ------------------------------------------- oversized-request recovery ---
GROQ_413 = (
    "All models in fallback chain failed:\n"
    "  - groq/openai/gpt-oss-20b: APIStatusError: Error code: 413 - {'error': {'message': "
    "'Request too large for model on tokens per minute (TPM): Limit 8000, Requested 9612', "
    "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)


def _big_messages():
    return [
        {"role": "user", "content": "research the topic"},
        {"role": "model", "content": [{"function_call": {"name": "web_search", "args": {}}}]},
        {"role": "user", "content": [{"function_response": {"name": "web_search", "response": {"result": "x" * 9000}}}]},
    ]


def test_groq_413_takes_diet_path_not_rate_limit_retry(tmp_memory, big_registry, monkeypatch):
    """The Groq 413 body contains 'rate_limit_exceeded' — it must be classified
    as oversized (diet), never as a transient rate limit (sleep + same retry)."""
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

    def behavior(messages, declarations):
        size = sum(len(str(m.get("content", ""))) for m in messages)
        if size > 2000:
            raise LLMError(GROQ_413)
        yield ("text", "slim ok")

    engine = _Engine(behavior)
    agent = AgentLoop(engine, big_registry, tmp_memory, persona=lambda **kw: "SYS")
    tb, _calls, err, msgs, _decls = agent._recover_or_give_up(
        _big_messages(), [], LLMError(GROQ_413)
    )
    assert err is None
    assert any("slim ok" in t for t in tb)
    assert slept == []  # never hit the transient rate-limit branch
    assert sum(len(str(m.get("content", ""))) for m in msgs) <= 2000


def test_transient_429_still_waits_and_retries(tmp_memory, big_registry, monkeypatch):
    """A genuine 429 (no oversized signals) waits 10s and retries unchanged —
    the request itself is fine, the provider is just busy."""
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    engine = _Engine(lambda m, d: iter([("text", "recovered")]))
    agent = AgentLoop(engine, big_registry, tmp_memory, persona=lambda **kw: "SYS")
    msgs = [{"role": "user", "content": "hi"}]
    tb, _calls, err, out_msgs, _decls = agent._recover_or_give_up(
        msgs, [], LLMError("... 429 ... rate_limit_exceeded, retry later ...")
    )
    assert err is None
    assert slept == [10]
    assert any("recovered" in t for t in tb)
    assert out_msgs is msgs  # retried unchanged


def test_emergency_diet_slims_the_system_prompt(tmp_memory, big_registry, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def behavior(messages, declarations):
        # even the diet is "too big" until the system prompt is swapped:
        # simulate by failing unless the prompt is the emergency one
        if "minimal context" not in engine.system_prompt:
            raise LLMError(GROQ_413)
        yield ("text", "emergency ok")

    engine = _Engine(behavior)
    agent = AgentLoop(engine, big_registry, tmp_memory, persona=lambda **kw: "SYS")
    engine.set_system_prompt("FULL PROMPT")
    tb, _calls, err, _msgs, _decls = agent._recover_or_give_up(
        _big_messages(), [], LLMError(GROQ_413)
    )
    assert err is None
    assert any("emergency ok" in t for t in tb)
    assert engine.system_prompt == AgentLoop.EMERGENCY_SYSTEM_PROMPT


# ------------------------------------------------------- SDK availability ---
def test_chain_skips_models_whose_sdk_is_missing(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["groq/llama-3.3-70b-versatile"])
    monkeypatch.setattr(
        LLMEngine, "_sdk_available", staticmethod(lambda provider: provider != "gemini")
    )
    engine = LLMEngine()
    status = engine.get_model_status()
    assert status["chain"] == ["groq/llama-3.3-70b-versatile"]
    assert status["sdk_skipped"] == ["gemini-2.5-flash"]


def test_empty_chain_error_names_missing_sdks(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gem-key")
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    monkeypatch.setattr(config, "PRIMARY_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(config, "FALLBACK_MODELS", [])
    monkeypatch.setattr(LLMEngine, "_sdk_available", staticmethod(lambda provider: False))
    engine = LLMEngine()
    with pytest.raises(LLMError, match="SDK missing for: gemini-2.5-flash"):
        list(engine.chat([{"role": "user", "content": "hi"}], []))


def test_gemini_stream_wraps_missing_sdk_in_actionable_error(monkeypatch):
    """A missing google-genai must raise the friendly LLMError, not a raw
    ModuleNotFoundError that buries itself in the chain report."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "google.genai" or name.startswith("google.genai."):
            raise ImportError("No module named 'google.genai'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    engine = LLMEngine.__new__(LLMEngine)  # skip __init__/chain building
    engine.system_prompt = ""
    engine._gemini_client = None
    with pytest.raises(LLMError, match="google-genai SDK not installed"):
        list(engine._gemini_stream([{"role": "user", "content": "hi"}], [], "gemini-2.5-flash"))
