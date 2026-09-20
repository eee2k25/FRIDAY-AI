"""THE BRAIN — ReAct agentic loop: Reason → Act → Observe → repeat until done.

Flow per user request:
  1. Save user message to memory, log a task
  2. Rebuild system prompt with live context, build message history
  3. Call the LLM (streaming) with the tool list
  4. Text only  → render, save, done
  5. Tool calls → print what FRIDAY is doing, execute each tool, feed results
     back to the LLM, repeat from 3
  6. Stops on: no more tool calls, MAX_AGENT_ITERATIONS, or total LLM failure

Resilience: tool failures are fed back to the LLM as "try another approach";
LLM failures switch model via the engine's fallback chain.
"""
from __future__ import annotations

import time

import config
from core import streaming
from core.llm_engine import LLMError

try:
    from rich.console import Console
except ImportError as e:  # fail fast with a clear error
    raise ImportError("rich not installed. Run: pip install -r requirements.txt") from e


class AgentLoop:
    def __init__(
        self,
        llm_engine,
        tool_registry,
        memory,
        persona=None,
        console: Console | None = None,
    ) -> None:
        """persona: optional callable (tool_list, recent_tasks, facts) -> str;
        defaults to persona.build_system_prompt when not supplied."""
        self.llm = llm_engine
        self.registry = tool_registry
        self.memory = memory
        self.console = console or Console()
        self._persona_builder = persona

    # -------------------------------------------------------- context ---
    def _build_system_prompt(self) -> str:
        if self._persona_builder is not None:
            return self._persona_builder(
                tool_list=self.registry.list_tools(),
                recent_tasks=self._format_recent_tasks(),
                facts=self._format_facts(),
            )
        from persona import build_system_prompt

        return build_system_prompt(
            tool_list=self.registry.list_tools(),
            recent_tasks=self._format_recent_tasks(),
            facts=self._format_facts(),
        )

    def _format_recent_tasks(self) -> str:
        tasks = self.memory.get_recent_tasks(5)
        if not tasks:
            return "(none yet)"
        lines = []
        for t in tasks:
            line = f"- [{t['status']}] {t['task_description']}"
            if t.get("result_summary"):
                line += f" → {str(t['result_summary'])[:100]}"
            lines.append(line)
        return "\n".join(lines)

    def _format_facts(self) -> str:
        facts = self.memory.get_all_facts()
        if not facts:
            return "(none stored yet)"
        return "\n".join(f"- {k}: {str(v)[:120]}" for k, v in list(facts.items())[:20])

    def _build_context(self, session_id: str) -> list[dict]:
        history = self.memory.get_history(session_id, last_n=config.HISTORY_WINDOW)
        messages: list[dict] = []
        for h in history:
            if h["role"] not in ("user", "model"):
                continue
            if not str(h["content"]).strip():
                continue
            messages.append({"role": h["role"], "content": str(h["content"])})
        return messages

    # ------------------------------------------------------------ run ---
    def _call_llm(self, messages: list[dict], declarations: list[dict]):
        """One streaming LLM call. Returns (text_buf, calls, stream_error)."""
        text_buf: list[str] = []
        calls: list[dict] = []
        stream_error: LLMError | None = None
        display = streaming.StreamingDisplay(self.console)
        with display:
            try:
                for kind, payload in self.llm.chat(messages, declarations):
                    if kind == "text":
                        text_buf.append(payload)
                        display.add_text(payload)
                    elif kind == "function_call":
                        calls.append(payload)
            except LLMError as e:
                stream_error = e
            except Exception as e:  # noqa: BLE001 — keep the loop alive
                stream_error = LLMError(f"{type(e).__name__}: {e}")
        return text_buf, calls, stream_error

    @staticmethod
    def _diet_messages(messages: list[dict], cap: int = 4000) -> list[dict]:
        """Copy of the history with oversized function responses trimmed —
        the recovery path when the request is too big for the model."""
        slim = []
        for m in messages:
            content = m.get("content")
            if not isinstance(content, list):
                slim.append(m)
                continue
            parts = []
            for part in content:
                if isinstance(part, dict) and "function_response" in part:
                    fr = part["function_response"]
                    resp = fr.get("response", {})
                    result = resp.get("result")
                    if isinstance(result, str) and len(result) > cap:
                        part = {
                            "function_response": {
                                "name": fr.get("name", ""),
                                "response": {
                                    "result": result[:cap]
                                    + f"\n... [context trimmed for retry, {len(result)} chars total]"
                                },
                            }
                        }
                parts.append(part)
            slim.append({**m, "content": parts})
        return slim

    # Tools the emergency diet still offers — small enough to fit a weak fallback model
    EMERGENCY_TOOLS = (
        "run_command",
        "run_powershell",
        "read_file",
        "write_file",
        "web_search",
        "fetch_webpage",
        "get_current_time",
        "save_fact",
        "recall_fact",
    )

    @classmethod
    def _emergency_diet(cls, messages: list[dict], cap: int = 1500) -> list[dict]:
        """Last-resort context: the original ask + the last tool exchange, hard-trimmed."""
        first_user = next(
            (m for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)),
            None,
        )
        last_model_idx = None
        for i, m in enumerate(messages):
            if m.get("role") == "model":
                last_model_idx = i
        slim: list[dict] = []
        if first_user is not None:
            slim.append(first_user)
        if last_model_idx is not None:
            slim.append(messages[last_model_idx])
            for m in messages[last_model_idx + 1 :]:
                if m.get("role") == "user" and isinstance(m.get("content"), list):
                    parts = []
                    for part in m["content"]:
                        if isinstance(part, dict) and "function_response" in part:
                            fr = part["function_response"]
                            resp = fr.get("response", {})
                            result = resp.get("result")
                            if isinstance(result, str) and len(result) > cap:
                                resp = {
                                    "result": result[:cap]
                                    + f"\n... [emergency trim, {len(result)} chars total]"
                                }
                            parts.append(
                                {"function_response": {"name": fr.get("name", ""), "response": resp}}
                            )
                    if parts:
                        slim.append({"role": "user", "content": parts})
        return slim or [messages[-1]]

    def _recover_or_give_up(
        self, messages: list[dict], declarations: list[dict], stream_error: LLMError
    ):
        """Self-heal a failed round in escalating stages:
        rate-limit → back off and retry; oversized → context diet, then emergency
        diet (original ask + last exchange + core tools only).
        Returns (text_buf, calls, error, messages, declarations)."""
        err = str(stream_error).lower()
        if any(k in err for k in ("429", "resource_exhausted", "rate_limit", "rate limit", "quota")):
            self.console.print("[dim]◈ Rate limited — waiting 10s and retrying…[/dim]")
            time.sleep(10)
            return self._call_llm(messages, declarations) + (messages, declarations)
        if any(k in err for k in ("413", "too large", "reduce your message", "tokens per minute", "payload")):
            self.console.print("[dim]◈ Request too big — trimming tool results and retrying…[/dim]")
            diet = self._diet_messages(messages)
            result = self._call_llm(diet, declarations)
            if result[2] is None:
                return result + (diet, declarations)
            self.console.print("[dim]◈ Still too big — emergency trim (core tools only)…[/dim]")
            emergency = self._emergency_diet(diet)
            core_decls = [d for d in declarations if d.get("name") in self.EMERGENCY_TOOLS]
            result = self._call_llm(emergency, core_decls)
            return result + (emergency, core_decls)
        return [], [], stream_error, messages, declarations

    def run(self, user_input: str, session_id: str) -> str:
        self.memory.add_message(session_id, "user", user_input)
        task_id = self.memory.log_task(user_input)
        self.llm.set_system_prompt(self._build_system_prompt())
        messages = self._build_context(session_id)
        declarations = self.registry.get_declarations()

        text = ""
        for iteration in range(1, config.MAX_AGENT_ITERATIONS + 1):
            self._print_thinking(iteration)
            text_buf, calls, stream_error = self._call_llm(messages, declarations)
            if stream_error is None and not text_buf and not calls:
                # Totally empty response (happens after large tool results) — retry once
                self.console.print("[dim]◈ Empty response — retrying once…[/dim]")
                text_buf, calls, stream_error = self._call_llm(messages, declarations)
            if stream_error is not None:
                text_buf, calls, stream_error, messages, declarations = self._recover_or_give_up(
                    messages, declarations, stream_error
                )
            if stream_error is not None:
                msg = (
                    f"⚠ Something broke mid-stream, Boss. The fallback chain was exhausted: "
                    f"{stream_error}. Ask again and I'll reroute."
                )
                self.memory.add_message(session_id, "model", msg)
                self._complete_task(task_id, f"stopped: {stream_error}", "error")
                self.console.print(f"[red]{msg}[/red]")
                return msg

            text = "".join(text_buf).strip()
            if text and calls:
                self.console.print(streaming.format_friday_note(text))

            if not calls:
                if not text:
                    text = "…"
                self._render_final(text)
                self.memory.add_message(session_id, "model", text)
                self._complete_task(task_id, text[:300], "done")
                return text

            # ---- ACT: append assistant turn, execute tools, feed results back ----
            assistant_content: list[dict] = []
            if text:
                assistant_content.append({"text": text})
            for c in calls:
                assistant_content.append({"function_call": {"name": c["name"], "args": c["args"]}})
            messages.append({"role": "model", "content": assistant_content})

            for c in calls:
                self._print_tool_start(c)
                res = self.registry.execute_tool(c["name"], c["args"])
                self.memory.log_tool_call(c["name"], c["args"], res["result"] or res["error"], res["success"])
                if res["success"]:
                    self._print_tool_done(c, res)
                    response = {"result": res["result"]}
                else:
                    self._print_tool_fail(c, res)
                    response = {
                        "result": "",
                        "error": res["error"],
                        "note": "Tool failed. Do NOT give up — try a different tool or approach.",
                    }
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"function_response": {"name": c["name"], "response": response}}
                        ],
                    }
                )

        # ---- safety limit reached ----
        partial = (
            f"Boss, I hit the {config.MAX_AGENT_ITERATIONS}-iteration safety limit on that task. "
            "Here is where things stand:\n" + (text if text else "(no final summary captured)")
        )
        self._render_final(partial)
        self.memory.add_message(session_id, "model", partial)
        self._complete_task(task_id, partial[:300], "partial")
        return partial

    def _complete_task(self, task_id: int, summary: str, status: str) -> None:
        try:
            self.memory.complete_task(task_id, summary, status)
        except Exception as e:  # noqa: BLE001
            config.logger.warning("could not complete task record: %s", e)

    # --------------------------------------------------- console style ---
    def _print_thinking(self, iteration: int) -> None:
        self.console.print(streaming.format_thinking(iteration))

    def _print_tool_start(self, c: dict) -> None:
        self.console.print(streaming.format_tool_start(c["name"], c.get("args", {})))

    def _print_tool_done(self, c: dict, res: dict) -> None:
        self.console.print(streaming.format_tool_done(res["result"]))

    def _print_tool_fail(self, c: dict, res: dict) -> None:
        self.console.print(streaming.format_tool_fail(res["error"]))

    def _render_final(self, text: str) -> None:
        streaming.render_final(self.console, text)
