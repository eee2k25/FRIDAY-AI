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
from core import streaming, tokens
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
        # compact=True: the tools are ALSO sent as structured declarations, so
        # the prompt carries one short line per tool, not the full descriptions.
        tool_list = self.registry.list_tools(compact=True)
        if self._persona_builder is not None:
            return self._persona_builder(
                tool_list=tool_list,
                recent_tasks=self._format_recent_tasks(),
                facts=self._format_facts(),
            )
        from persona import build_system_prompt

        return build_system_prompt(
            tool_list=tool_list,
            recent_tasks=self._format_recent_tasks(),
            facts=self._format_facts(),
        )

    # -------------------------------------------------- tool filtering ---
    @staticmethod
    def _latest_text(messages: list[dict]) -> str:
        """Newest user/model text in the conversation — the relevance query."""
        for m in reversed(messages):
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                return c
            if isinstance(c, list):
                txt = " ".join(
                    p["text"] for p in c if isinstance(p, dict) and p.get("text")
                ).strip()
                if txt:
                    return txt
        return ""

    @staticmethod
    def _recent_tool_names(messages: list[dict], limit: int = 12) -> list[str]:
        """Tools already used in this conversation, newest first — the model is
        likely to keep using them, so they must stay declared."""
        names: list[str] = []
        for m in reversed(messages):
            content = m.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict):
                    fc = part.get("function_call")
                    if fc and fc.get("name") and fc["name"] not in names:
                        names.append(fc["name"])
            if len(names) >= limit:
                break
        return names

    def _select_tools(self, messages: list[dict], pool: list[dict]) -> list[dict]:
        """Curate the tool declarations for this turn.

        The full 108-tool declaration set costs ~8.6k tokens on every call —
        more than weak fallback providers allow per minute (Groq on-demand:
        8k TPM). Filtering to the relevant subset keeps requests small enough
        for the whole chain. Disable with TOOL_FILTER=False in .env.
        """
        if not config.TOOL_FILTER_ENABLED:
            return pool
        selected = self.registry.select_declarations(
            query=self._latest_text(messages),
            cap=config.MAX_TOOLS_PER_CALL,
            extra_names=self._recent_tool_names(messages),
            pool=pool,
        )
        if len(selected) < len(pool):
            config.logger.debug(
                "tool filter: %d/%d declarations this turn", len(selected), len(pool)
            )
        return selected

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

    # System prompt for the emergency diet. The normal prompt carries the full
    # tool list (~3k tokens) which alone can exceed a weak provider's limit,
    # so the last-resort retry gets a minimal prompt to match the core tools.
    EMERGENCY_SYSTEM_PROMPT = (
        "You are FRIDAY, an autonomous AI agent. A provider token limit forced a "
        "minimal context: you have the original request, the latest tool "
        "exchange, and a small core tool set. Complete the task with what you "
        "have. Be brief, decisive, and exact."
    )

    # The REQUEST ITSELF is too big for a provider — retrying unchanged can
    # never succeed, so shrink it. Checked BEFORE the transient rate-limit
    # branch: Groq's 413 body contains 'rate_limit_exceeded', which must NOT
    # be mistaken for a transient 429 (that bug made every oversized request
    # sleep 10s, retry identically, and fail again).
    _OVERSIZED_SIGNALS = (
        "413",
        "request too large",
        "too many tokens",
        "tokens per minute",
        "reduce your message size",
        "payload too large",
        "context length",
        "context window",
        "maximum context",
        "prompt is too long",
        "input too long",
    )
    # Transient overload — waiting and retrying unchanged is the right move.
    _RETRY_SIGNALS = (
        "429",
        "resource_exhausted",
        "rate_limit",
        "rate limit",
        "quota",
        "too many requests",
        "overloaded",
        "temporarily unavailable",
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
        oversized request → context diet, then emergency diet (original ask +
        last exchange + core tools + minimal system prompt); transient
        rate-limit/overload → back off and retry unchanged.
        Returns (text_buf, calls, error, messages, declarations)."""
        err = str(stream_error).lower()
        if any(k in err for k in self._OVERSIZED_SIGNALS):
            self.console.print("[dim]◈ Request too big — trimming tool results and retrying…[/dim]")
            diet = self._diet_messages(messages)
            result = self._call_llm(diet, declarations)
            if result[2] is None:
                return result + (diet, declarations)
            self.console.print("[dim]◈ Still too big — emergency trim (core tools only)…[/dim]")
            emergency = self._emergency_diet(diet)
            core_decls = [d for d in declarations if d.get("name") in self.EMERGENCY_TOOLS]
            self.llm.set_system_prompt(self.EMERGENCY_SYSTEM_PROMPT)
            result = self._call_llm(emergency, core_decls)
            return result + (emergency, core_decls)
        if any(k in err for k in self._RETRY_SIGNALS):
            self.console.print("[dim]◈ Rate limited — waiting 10s and retrying…[/dim]")
            time.sleep(10)
            return self._call_llm(messages, declarations) + (messages, declarations)
        return [], [], stream_error, messages, declarations

    def _enforce_token_budget(self, messages: list[dict]) -> list[dict]:
        """Shed the oldest turns before the context outgrows MAX_CONTEXT_TOKENS.

        Cheaper and far less lossy than waiting for the provider to reject the
        request and falling into the emergency diet.
        """
        trimmed, dropped = tokens.trim_to_budget(messages, config.MAX_CONTEXT_TOKENS)
        if dropped:
            config.logger.info("context budget: dropped %d oldest message(s)", dropped)
            self.console.print(
                f"[dim]◈ Context budget reached — dropped {dropped} older message(s).[/dim]"
            )
        return trimmed

    def run(self, user_input: str, session_id: str) -> str:
        self.memory.add_message(session_id, "user", user_input)
        task_id = self.memory.log_task(user_input)
        self.llm.set_system_prompt(self._build_system_prompt())
        messages = self._build_context(session_id)
        declarations = self.registry.get_declarations()

        text = ""
        for iteration in range(1, config.MAX_AGENT_ITERATIONS + 1):
            self._print_thinking(iteration)
            messages = self._enforce_token_budget(messages)
            declarations = self._select_tools(messages, declarations)
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
