"""FRIDAY offline self-test — no API keys needed.

Validates: memory, tool auto-discovery, file/math tools, and the full ReAct
agent loop end-to-end using a mock LLM engine.

Run:  python selftest.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASSED, FAILED = 0, 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


class FakeEngine:
    """Mock LLM: scripted events per round — round 1 calls a tool, round 2 answers."""

    def __init__(self, script: list[list[tuple]]) -> None:
        self.script = script
        self.round = 0
        self.system_prompt = ""

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def chat(self, messages, declarations):
        events = self.script[min(self.round, len(self.script) - 1)]
        self.round += 1
        for e in events:
            yield e

    def get_model_status(self) -> dict:
        return {"active_model": "fake", "provider": "none", "chain": ["fake"], "calls": {}, "last_error": None}


def main() -> int:
    print("FRIDAY self-test (offline)\n")
    tmp = Path(tempfile.mkdtemp(prefix="friday_selftest_"))
    try:
        # ---- 1. memory ------------------------------------------------
        print("[1/5] memory (SQLite)")
        from core.memory import FridayMemory

        mem = FridayMemory(db_path=tmp / "test_memory.db")
        mem.add_message("s1", "user", "hello")
        mem.add_message("s1", "model", "hi Boss")
        check("add/get history", len(mem.get_history("s1")) == 2)
        mem.save_fact("boss_name", "Selftest")
        check("save/recall fact", mem.get_fact("boss_name") == "Selftest")
        mem.save_fact("boss_name", "Selftest2", source="friday")
        check("fact upsert", mem.get_fact("boss_name") == "Selftest2")
        tid = mem.log_task("self-test task")
        mem.complete_task(tid, "ok", "done")
        check("task lifecycle", mem.get_recent_tasks(1)[0]["status"] == "done")
        mem.log_tool_call("read_file", {"path": "x"}, "result", True)
        check("tool usage log", mem.get_session_summary()["tool_calls"] == 1)
        check("search history", any("hello" in h["content"] for h in mem.search_history("hello")))
        check("clear session keeps facts", mem.clear_session("s1") == 2 and mem.get_fact("boss_name") is not None)

        # ---- 2. tool registry ------------------------------------------
        print("\n[2/5] tool registry (auto-discover)")
        from core.tool_registry import ToolRegistry
        from tools import memory_tools

        registry = ToolRegistry()
        memory_tools.bind_memory(mem)
        disc = registry.auto_discover()
        names = set(registry.tools)
        expected = {
            "read_file", "write_file", "list_directory", "search_files", "create_folder",
            "copy_file", "delete_file", "get_file_info",
            "web_search", "fetch_webpage", "search_and_fetch", "read_pdf_url", "read_local_pdf",
            "create_word_doc", "read_word_doc", "append_to_word_doc", "create_project_report",
            "create_excel", "read_excel", "append_excel_row",
            "run_command", "run_python_code", "open_application", "get_system_info",
            "list_running_processes", "get_current_time",
            "analyze_code", "write_and_run_code", "fix_python_error", "git_status",
            "deep_research", "research_and_write_report", "summarize_document", "compare_sources",
            "calculate", "unit_convert", "solve_equation",
            "save_fact", "recall_fact", "list_facts", "search_memory",
        }
        missing = expected - names
        check(f"tools discovered ({len(names)} loaded)", len(names) >= 35, f"missing: {missing or disc['errors']}")
        decls = registry.get_declarations()
        check("gemini declarations well-formed", all(d.get("name") and d.get("description") and d.get("parameters", {}).get("type") == "object" for d in decls))
        bad = registry.execute_tool("does_not_exist", {})
        check("unknown tool handled", bad["success"] is False and "Unknown tool" in bad["error"])

        # regression guard: every module-level constant referenced in code must exist
        # (catches the v1.0.3 _COMPILE_CAP incident — a use shipped without its definition)
        import ast as _ast
        import importlib

        dangling: list[str] = []
        for mod_name in (
            "tools.research_tools", "tools.browser_tools", "tools.document_tools",
            "tools.file_tools", "tools.system_tools", "tools.code_tools",
            "tools.math_tools", "tools.memory_tools",
            "core.agent_loop", "core.llm_engine", "core.memory", "core.tool_registry",
        ):
            mod = importlib.import_module(mod_name)
            tree = _ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
            defined = set(dir(mod))
            # include names imported at any scope (e.g. `from ddgs import DDGS` inside a function)
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    defined.update(a.asname or a.name.split(".")[0] for a in node.names)
                elif isinstance(node, _ast.ImportFrom):
                    defined.update(a.asname or a.name for a in node.names)
            used = {n.id for n in _ast.walk(tree) if isinstance(n, _ast.Name) and isinstance(n.ctx, _ast.Load)}
            for name in used:
                if name.isupper() and name not in defined:
                    dangling.append(f"{mod_name}.{name}")
        check("no dangling constants in any module", not dangling, str(dangling))

        # ---- 3. tool execution (no network) -----------------------------
        print("\n[3/5] tool execution")
        target = tmp / "sub" / "hello.txt"
        r = registry.execute_tool("write_file", {"path": str(target), "content": "hello friday\nline two\n"})
        check("write_file", r["success"] and target.exists(), r["error"] or "")
        r = registry.execute_tool("read_file", {"path": str(target)})
        check("read_file", r["success"] and "hello friday" in r["result"])
        r = registry.execute_tool("search_files", {"directory": str(tmp), "query": "friday"})
        check("search_files", r["success"] and "hello.txt" in r["result"])
        r = registry.execute_tool("list_directory", {"path": str(tmp / "sub")})
        check("list_directory", r["success"] and "hello.txt" in r["result"])
        r = registry.execute_tool("delete_file", {"path": str(target), "confirm": True})
        check("delete_file gated", r["success"] and target.exists() and "explicitly" in r["result"])
        nested = tmp / "sub" / "nested" / "deep.txt"
        registry.execute_tool("write_file", {"path": str(nested), "content": "deep"})
        r = registry.execute_tool("list_directory", {"path": str(tmp / "sub"), "recursive": "True", "depth": 5})
        check("list_directory recursive", r["success"] and "deep.txt" in r["result"], r["error"] or "")
        r = registry.execute_tool("calculate", {"expression": "2*(3+4)**2/7"})
        check("calculate", r["success"] and "= 14" in r["result"], r["error"] or r["result"])
        r = registry.execute_tool("get_current_time", {})
        check("get_current_time", r["success"] and "UTC offset" in r["result"])
        try:
            import pint  # noqa: F401
            r = registry.execute_tool("unit_convert", {"value": 100, "from_unit": "kilometers", "to_unit": "miles"})
            check("unit_convert (pint)", r["success"] and "62.1" in r["result"], r["error"] or r["result"])
        except ImportError:
            print("  ~ unit_convert skipped (pint not installed in this env)")
        try:
            import sympy  # noqa: F401
            r = registry.execute_tool("solve_equation", {"equation": "2x + 5 = 9"})
            check("solve_equation (sympy)", r["success"] and "x = 2" in r["result"], r["result"])
        except ImportError:
            print("  ~ solve_equation skipped (sympy not installed in this env)")
        r = registry.execute_tool("run_python_code", {"code": "print(6*7)"})
        check("run_python_code", r["success"] and "42" in r["result"], r["error"] or r["result"])
        import os as _os
        r = registry.execute_tool("run_powershell", {"command": "Get-Date"})
        if _os.name == "nt":
            check("run_powershell", r["success"] and "EXIT CODE: 0" in r["result"], r["error"] or r["result"])
        else:
            check(
                "run_powershell graceful (non-Windows)",
                r["success"] is False and "PowerShell" in (r["error"] or ""),
                r["error"] or "",
            )
        r = registry.execute_tool("check_own_logs", {"lines": 5})
        check("check_own_logs", r["success"] and len(r["result"]) > 0, r["error"] or "")

        try:
            import docx  # noqa: F401
            docx_path = tmp / "doc.docx"
            r = registry.execute_tool("create_word_doc", {"path": str(docx_path), "title": "T", "content": "# H1\n- item\n**bold**"})
            check("create_word_doc (docx)", r["success"] and docx_path.exists(), r["error"] or "")
            r = registry.execute_tool("read_word_doc", {"path": str(docx_path)})
            check("read_word_doc", r["success"] and "# H1" in r["result"] and "- item" in r["result"])
        except ImportError:
            print("  ~ word tools skipped (python-docx not installed in this env)")

        # ---- 4. agent loop (mock LLM, full ReAct) ------------------------
        print("\n[4/5] agent loop (ReAct with mock LLM)")
        from core.agent_loop import AgentLoop

        from io import StringIO
        from rich.console import Console as RichConsole

        engine = FakeEngine(
            [
                [("function_call", {"name": "get_current_time", "args": {}})],
                [("text", "Done, Boss. The time is now known.")],
            ]
        )
        agent = AgentLoop(engine, registry, mem, console=RichConsole(file=StringIO()))
        out = agent.run("what time is it?", "selftest-session")
        check("loop reaches final answer", "Done, Boss" in out)
        check("loop streamed final to memory", any("Done, Boss" in h["content"] for h in mem.get_history("selftest-session")))
        su = mem.get_session_summary()
        check("tool call logged in loop", su["tool_calls"] >= 1)

        # tool-failure resilience: mock calls a tool that errors, then recovers
        engine2 = FakeEngine(
            [
                [("function_call", {"name": "read_file", "args": {"path": str(tmp / "nope.txt")}})],
                [("text", "Found a different way, Boss. That file does not exist — verified.")],
            ]
        )
        agent2 = AgentLoop(engine2, registry, mem, console=RichConsole(file=StringIO()))
        out2 = agent2.run("read the missing file", "selftest-session")
        check("loop survives tool failure", "different way" in out2)

        # mid-stream failure must be VISIBLE (never a silent turn)
        class FlakyEngine:
            def set_system_prompt(self, p) -> None:
                pass

            def chat(self, messages, declarations):
                yield ("text", "partial...")
                raise RuntimeError("boom mid-stream")

            def get_model_status(self) -> dict:
                return {"active_model": "flaky"}

        buf = StringIO()
        agent3 = AgentLoop(FlakyEngine(), registry, mem, console=RichConsole(file=buf))
        out3 = agent3.run("do the thing", "selftest-session")
        check("mid-stream failure is visible", "⚠" in out3 and "⚠" in buf.getvalue())

        # empty response triggers exactly one automatic retry
        class EmptyEngine:
            def __init__(self) -> None:
                self.calls = 0
                self.system_prompt = ""

            def set_system_prompt(self, p) -> None:
                self.system_prompt = p

            def chat(self, messages, declarations):
                self.calls += 1
                if self.calls == 1:
                    return
                    yield  # noqa: RET503 — first call returns nothing
                yield ("text", "Recovered, Boss.")

            def get_model_status(self) -> dict:
                return {"active_model": "empty"}

        e5 = EmptyEngine()
        buf5 = StringIO()
        agent5 = AgentLoop(e5, registry, mem, console=RichConsole(file=buf5))
        out5 = agent5.run("speak", "selftest-session")
        check("empty response auto-retries", "Recovered, Boss." in out5 and e5.calls == 2)

        # context-diet recovery: oversized requests are trimmed and retried
        from core.llm_engine import LLMError

        class SizeSensitiveEngine:
            def __init__(self) -> None:
                self.system_prompt = ""

            def set_system_prompt(self, p) -> None:
                self.system_prompt = p

            def chat(self, messages, declarations):
                size = sum(len(str(m.get("content", ""))) for m in messages)
                if size > 8000:
                    raise RuntimeError("Error code: 413 - Request too large for model")
                yield ("text", "Recovered with slim context, Boss.")

            def get_model_status(self) -> dict:
                return {"active_model": "size"}

        big_msgs = [
            {"role": "user", "content": "research the topic"},
            {"role": "model", "content": [{"function_call": {"name": "deep_research", "args": {}}}]},
            {
                "role": "user",
                "content": [
                    {"function_response": {"name": "deep_research", "response": {"result": "x" * 20000}}}
                ],
            },
        ]
        agent_sz = AgentLoop(SizeSensitiveEngine(), registry, mem, console=RichConsole(file=StringIO()))
        tb, _cl, err, new_msgs, _decls = agent_sz._recover_or_give_up(
            big_msgs, [], LLMError("All models in fallback chain failed:\n  - groq/x: 413 Request too large")
        )
        check(
            "context-diet recovery",
            err is None
            and any("Recovered" in t for t in tb)
            and sum(len(str(m.get("content", ""))) for m in new_msgs) < 8000,
        )

        # ---- 5. persona ---------------------------------------------------
        print("\n[5/5] persona")
        from persona import build_system_prompt

        prompt = build_system_prompt(registry.list_tools(), mem._format_recent_tasks() if hasattr(mem, "_format_recent_tasks") else "(none)", "(test)")
        check("prompt has identity", "FRIDAY" in prompt and "Boss" in prompt)
        check("prompt injects tools", "read_file" in prompt and "deep_research" in prompt)
        check("prompt injects context", "Working directory" in prompt and "Date/time" in prompt)

        # ---- summary -------------------------------------------------------
        print(f"\n{'=' * 46}\nRESULT: {PASSED} passed, {FAILED} failed\n{'=' * 46}")
        return 1 if FAILED else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
