"""Tests for dynamic tool registration and the safe-call contract."""
from __future__ import annotations

import config


def _decl(name, props=None):
    return {
        "name": name,
        "description": f"test tool {name}",
        "parameters": {"type": "object", "properties": props or {}},
    }


def test_register_and_execute(registry):
    registry.register_tool("echo", lambda text: f"echo:{text}", _decl("echo"))
    out = registry.execute_tool("echo", {"text": "hi"})
    assert out == {"success": True, "result": "echo:hi", "error": None}


def test_declaration_name_is_forced_to_registered_name(registry):
    registry.register_tool("real", lambda: "x", _decl("wrong_name"))
    assert registry.get_declarations()[0]["name"] == "real"


def test_missing_declaration_is_synthesised_from_docstring(registry):
    def helper():
        """Does a helpful thing."""
        return "ok"

    registry.register_tool("helper", helper, {})
    assert registry.get_declarations()[0]["description"] == "Does a helpful thing."


def test_unknown_tool_lists_alternatives(registry):
    registry.register_tool("alpha", lambda: "a", _decl("alpha"))
    out = registry.execute_tool("beta", {})
    assert out["success"] is False
    assert "alpha" in out["error"]


def test_bad_arguments_reported_not_raised(registry):
    registry.register_tool("needs_x", lambda x: x, _decl("needs_x"))
    out = registry.execute_tool("needs_x", {"y": 1})
    assert out["success"] is False
    assert "Argument error" in out["error"]


def test_tool_exception_is_captured(registry):
    def boom():
        raise ValueError("kaboom")

    registry.register_tool("boom", boom, _decl("boom"))
    out = registry.execute_tool("boom", {})
    assert out["success"] is False
    assert "ValueError: kaboom" in out["error"]


def test_non_string_results_are_json_encoded(registry):
    registry.register_tool("dicty", lambda: {"a": 1}, _decl("dicty"))
    assert '"a": 1' in registry.execute_tool("dicty", {})["result"]


def test_oversized_results_are_truncated(registry, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_RESULT_CHARS", 50)
    registry.register_tool("big", lambda: "x" * 500, _decl("big"))
    out = registry.execute_tool("big", {})
    assert "truncated" in out["result"]
    assert len(out["result"]) < 200


def test_non_dict_args_are_tolerated(registry):
    registry.register_tool("nil", lambda: "ok", _decl("nil"))
    assert registry.execute_tool("nil", "not-a-dict")["success"] is True


def test_auto_discover_loads_the_real_tool_package(registry):
    report = registry.auto_discover()
    assert report["loaded"] >= 1
    assert registry.tools, "no tools registered from tools/"


def test_gemini_tools_wrapper_shape(registry):
    registry.register_tool("a", lambda: "", _decl("a"))
    wrapped = registry.get_gemini_tools()
    assert wrapped and "function_declarations" in wrapped[0]


def test_gemini_tools_is_none_when_empty(registry):
    assert registry.get_gemini_tools() is None


def test_list_tools_placeholder_when_empty(registry):
    assert registry.list_tools() == "(no tools loaded)"
