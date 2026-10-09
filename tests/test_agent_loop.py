"""Tests for the ReAct loop: context diets, tool round-trips, iteration caps."""
from __future__ import annotations

import config
from core.agent_loop import AgentLoop
from core.tool_registry import ToolRegistry


class FakeEngine:
    """Replays a scripted list of event-lists, one per chat() call."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []
        self.system_prompt = ""

    def set_system_prompt(self, prompt):
        self.system_prompt = prompt

    def chat(self, messages, declarations):
        self.calls.append(messages)
        events = self.scripts.pop(0) if self.scripts else [("text", "done")]
        yield from events

    def get_model_status(self):
        return {"active_model": "fake", "provider": "fake", "chain": ["fake"], "calls": {}, "last_error": None}


def _agent(scripts, memory, tools=None):
    reg = ToolRegistry()
    for name, fn in (tools or {}).items():
        reg.register_tool(name, fn, {"name": name, "description": name,
                                     "parameters": {"type": "object", "properties": {}}})
    engine = FakeEngine(scripts)
    return AgentLoop(engine, reg, memory, persona=lambda **kw: "SYS"), engine, reg


def test_plain_answer_is_saved_to_memory(tmp_memory):
    agent, _, _ = _agent([[("text", "Hello Boss")]], tmp_memory)
    agent.run("hi", "s1")
    hist = tmp_memory.get_history("s1")
    assert hist[0]["content"] == "hi"
    assert "Hello Boss" in hist[-1]["content"]


def test_tool_call_result_is_fed_back_and_answered(tmp_memory):
    scripts = [
        [("function_call", {"name": "ping", "args": {}})],
        [("text", "The answer is pong")],
    ]
    agent, engine, _ = _agent(scripts, tmp_memory, {"ping": lambda: "pong"})
    agent.run("ping it", "s2")
    assert len(engine.calls) == 2
    second = engine.calls[1]
    assert any("pong" in str(m.get("content")) for m in second)


def test_failing_tool_is_reported_back_not_fatal(tmp_memory):
    def boom():
        raise RuntimeError("disk on fire")

    scripts = [
        [("function_call", {"name": "boom", "args": {}})],
        [("text", "I worked around it")],
    ]
    agent, engine, _ = _agent(scripts, tmp_memory, {"boom": boom})
    agent.run("go", "s3")
    assert any("disk on fire" in str(m.get("content")) for m in engine.calls[1])


def test_tool_usage_is_logged(tmp_memory):
    scripts = [[("function_call", {"name": "ping", "args": {}})], [("text", "ok")]]
    agent, _, _ = _agent(scripts, tmp_memory, {"ping": lambda: "pong"})
    agent.run("go", "s4")
    assert tmp_memory.get_session_summary()["tool_calls"] == 1


def test_iteration_cap_is_enforced(tmp_memory, monkeypatch):
    monkeypatch.setattr(config, "MAX_AGENT_ITERATIONS", 3)
    loop_forever = [[("function_call", {"name": "ping", "args": {}})] for _ in range(20)]
    agent, engine, _ = _agent(loop_forever, tmp_memory, {"ping": lambda: "pong"})
    agent.run("spin", "s5")
    assert len(engine.calls) <= 3


def test_task_is_recorded_for_every_run(tmp_memory):
    agent, _, _ = _agent([[("text", "sure")]], tmp_memory)
    agent.run("summarise this", "s6")
    tasks = tmp_memory.get_recent_tasks(1)
    assert tasks and "summarise this" in tasks[0]["task_description"]


def test_diet_messages_trims_big_tool_results():
    msgs = [{"role": "user", "content": [
        {"function_response": {"name": "read", "response": {"result": "y" * 9000}}}
    ]}]
    out = AgentLoop._diet_messages(msgs, cap=100)
    body = out[0]["content"][0]["function_response"]["response"]["result"]
    assert len(body) < 400
    assert "context trimmed" in body


def test_diet_messages_leaves_plain_text_alone():
    msgs = [{"role": "user", "content": "short question"}]
    assert AgentLoop._diet_messages(msgs) == msgs


def test_emergency_diet_keeps_first_ask_and_last_exchange():
    msgs = [
        {"role": "user", "content": "the original ask"},
        {"role": "model", "content": [{"text": "thinking"}]},
        {"role": "user", "content": [
            {"function_response": {"name": "t", "response": {"result": "z" * 5000}}}
        ]},
    ]
    out = AgentLoop._emergency_diet(msgs, cap=50)
    assert out[0]["content"] == "the original ask"
    assert "emergency trim" in out[-1]["content"][0]["function_response"]["response"]["result"]


def test_emergency_diet_never_returns_empty():
    msgs = [{"role": "user", "content": [{"text": "only a part"}]}]
    assert AgentLoop._emergency_diet(msgs)


def _dead_engine(chain):
    from core.llm_engine import LLMError

    class DeadEngine:
        def __init__(self):
            self.system_prompt = ""

        def set_system_prompt(self, prompt):
            self.system_prompt = prompt

        def chat(self, messages, declarations):
            raise LLMError("Ollama HTTP 504 at http://ollama.local — check `ollama serve`")
            yield  # pragma: no cover

        def get_model_status(self):
            return {
                "active_model": chain[0],
                "provider": "ollama",
                "chain": list(chain),
                "calls": {},
                "last_error": None,
            }

    return DeadEngine()


def test_single_model_failure_names_the_model_and_doctor(tmp_memory):
    """One configured model → no 'exhausted fallback chain' blame; name the
    model and point at the diagnosis command."""
    agent = AgentLoop(
        _dead_engine(["ollama/llama3.2"]), ToolRegistry(), tmp_memory, persona=lambda **kw: "SYS"
    )
    out = agent.run("hi", "s-dead")
    assert "ollama/llama3.2" in out
    assert "--doctor" in out
    assert "fallback chain was exhausted" not in out


def test_multi_model_failure_keeps_the_exhausted_chain_message(tmp_memory):
    agent = AgentLoop(
        _dead_engine(["gemini-a", "groq/b"]), ToolRegistry(), tmp_memory, persona=lambda **kw: "SYS"
    )
    out = agent.run("hi", "s-dead2")
    assert "fallback chain was exhausted" in out
