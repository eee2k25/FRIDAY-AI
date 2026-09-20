"""LLM engine — Gemini primary with automatic fallback chain (Gemini → Groq).

- Gemini via the official `google-genai` SDK (streaming + native function calling)
- Groq via its OpenAI-compatible API (streaming + tool calls)
- Message format translation between internal, google-genai and OpenAI-style
  (Groq) formats
- Auto model switching on API errors, rate limits and missing keys
"""
from __future__ import annotations

import json
import re

import config


class LLMError(Exception):
    """Fatal engine error — no model in the chain could serve the request."""


class LLMStreamError(LLMError):
    """Error raised mid-stream."""


class LLMEngine:
    def __init__(self, system_prompt: str = "") -> None:
        self.system_prompt = system_prompt
        self._chain = self._build_chain()
        self._model_index = 0
        self._stats: dict[str, int] = {}
        self._last_error: str | None = None
        self._groq_client = None
        self._gemini_client = None
        if not self._chain:
            config.logger.error(
                "No usable API keys in .env — add GEMINI_API_KEY and/or GROQ_API_KEY"
            )

    # --------------------------------------------------- chain mgmt ---
    @staticmethod
    def _normalize_model(m: str) -> str:
        """Strip whitespace and Groq UI labels like ' - on_demand' from model names."""
        m = m.strip()
        m = re.sub(r"\s*[-–]\s*on[_ ]?demand$", "", m, flags=re.IGNORECASE)
        return m.strip()

    def _build_chain(self) -> list[tuple[str, str]]:
        chain: list[tuple[str, str]] = []
        seen: set[str] = set()
        models = [config.PRIMARY_MODEL] + list(config.FALLBACK_MODELS)
        for m in models:
            m = self._normalize_model(m)
            if not m or m in seen:
                continue
            seen.add(m)
            if m.lower().startswith("groq/"):
                if config.GROQ_API_KEY:
                    chain.append((m, "groq"))
            else:
                if config.GEMINI_API_KEY:
                    chain.append((m, "gemini"))
        return chain

    def set_primary_model(self, model_name: str) -> None:
        """Switch the primary model at runtime (used by the `model` command)."""
        old = config.PRIMARY_MODEL
        config.PRIMARY_MODEL = model_name
        self._chain = self._build_chain()
        self._model_index = 0
        config.logger.info("primary model switched: %s -> %s", old, model_name)

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    # ------------------------------------------------------- public ---
    def chat(self, messages: list[dict], declarations: list[dict]):
        """Yield ("text", str) and ("function_call", {name, args}) events.

        Falls back down the model chain automatically on API errors.
        `messages` use the internal format:
            {"role": "user"|"model", "content": str | [parts]}
        where parts are {"text": ...} / {"function_call": {name, args}} /
        {"function_response": {name, response}}.
        """
        if not self._chain:
            raise LLMError("No API keys configured. Put GEMINI_API_KEY and/or GROQ_API_KEY in .env")
        errors: list[str] = []
        attempts = 0
        while attempts <= len(self._chain):
            idx = (self._model_index + attempts) % len(self._chain)
            model_name, provider = self._chain[idx]
            self._model_index = idx
            self._stats[model_name] = self._stats.get(model_name, 0) + 1
            config.logger.info("model call #%d on %s", self._stats[model_name], model_name)
            try:
                if provider == "gemini":
                    yield from self._gemini_stream(messages, declarations, model_name)
                else:
                    yield from self._groq_stream(messages, declarations, model_name)
                self._last_error = None
                return
            except Exception as e:  # noqa: BLE001 — any API failure triggers fallback
                line = f"{model_name}: {type(e).__name__}: {e}"
                self._last_error = line
                errors.append(line)
                config.logger.warning("model %s failed (%s) — trying next in chain", model_name, e)
                attempts += 1
        raise LLMError("All models in fallback chain failed:\n" + "\n".join(f"  - {e}" for e in errors))

    def get_model_status(self) -> dict:
        active = self._chain[self._model_index] if self._chain else ("(none)", None)
        return {
            "active_model": active[0],
            "provider": active[1],
            "chain": [m for m, _ in self._chain],
            "calls": dict(self._stats),
            "last_error": self._last_error,
        }

    # ------------------------------------------------------- gemini ---
    def _get_gemini_client(self):
        if self._gemini_client is None:
            try:
                from google import genai
            except ImportError as e:
                raise LLMError("google-genai SDK not installed. Run: pip install -r requirements.txt") from e
            self._gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
        return self._gemini_client

    @staticmethod
    def _json_schema_to_types(ps: dict):
        """JSON-schema property dict → google.genai.types.Schema."""
        from google.genai import types

        tmap = {
            "string": types.Type.STRING,
            "integer": types.Type.INTEGER,
            "number": types.Type.NUMBER,
            "boolean": types.Type.BOOLEAN,
            "array": types.Type.ARRAY,
            "object": types.Type.OBJECT,
        }
        schema = types.Schema(type=tmap.get(str(ps.get("type", "string")).lower(), types.Type.STRING))
        if ps.get("description"):
            schema.description = ps["description"]
        if ps.get("enum"):
            vals = [str(v) for v in ps["enum"]]
            # field is `enum_` in older google-genai releases, `enum` in current ones
            if "enum_" in type(schema).model_fields:
                schema.enum_ = vals
            else:
                schema.enum = vals
        if ps.get("items"):
            schema.items = LLMEngine._json_schema_to_types(ps["items"])
        if ps.get("properties"):
            schema.properties = {
                k: LLMEngine._json_schema_to_types(v) for k, v in ps["properties"].items()
            }
        return schema

    @classmethod
    def _to_genai_declarations(cls, declarations: list[dict]):
        """Plain JSON-schema declarations → google.genai FunctionDeclarations."""
        from google.genai import types

        out = []
        for d in declarations:
            params = d.get("parameters") or {}
            schema_kwargs = {}
            if params.get("properties"):
                schema_kwargs["properties"] = {
                    k: cls._json_schema_to_types(v) for k, v in params["properties"].items()
                }
            if params.get("required"):
                schema_kwargs["required"] = list(params["required"])
            schema = types.Schema(type=types.Type.OBJECT, **schema_kwargs)
            out.append(
                types.FunctionDeclaration(
                    name=d["name"],
                    description=d.get("description", ""),
                    parameters=schema,
                )
            )
        return out

    @staticmethod
    def _to_genai_contents(messages: list[dict]):
        from google.genai import types

        contents = []
        for m in messages:
            role = "model" if m.get("role") == "model" else "user"
            content = m.get("content", "")
            parts = []
            if isinstance(content, str):
                if content.strip():
                    parts.append(types.Part.from_text(text=content))
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if "text" in part and part["text"]:
                        parts.append(types.Part.from_text(text=part["text"]))
                    elif "function_call" in part:
                        fc = part["function_call"]
                        parts.append(
                            types.Part.from_function_call(
                                name=fc.get("name", ""), args=fc.get("args", {})
                            )
                        )
                    elif "function_response" in part:
                        fr = part["function_response"]
                        parts.append(
                            types.Part.from_function_response(
                                name=fr.get("name", ""), response=fr.get("response", {})
                            )
                        )
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        while contents and contents[0].role != "user":
            contents.pop(0)
        return contents

    def _gemini_stream(self, messages: list[dict], declarations: list[dict], model_name: str):
        from google.genai import types

        client = self._get_gemini_client()
        contents = self._to_genai_contents(messages)
        if not contents:
            raise LLMError("Empty conversation — nothing to send")

        cfg_kwargs = {}
        if self.system_prompt:
            cfg_kwargs["system_instruction"] = self.system_prompt
        if declarations:
            cfg_kwargs["tools"] = [
                types.Tool(function_declarations=self._to_genai_declarations(declarations))
            ]
        stream = client.models.generate_content_stream(
            model=model_name, contents=contents, config=types.GenerateContentConfig(**cfg_kwargs)
        )
        for chunk in stream:
            candidates = getattr(chunk, "candidates", None)
            if not candidates:
                continue  # safety-blocked or malformed chunk
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or [] if content else []
            for part in parts:
                text = getattr(part, "text", None)
                if text:
                    yield ("text", text)
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    args = fc.args or {}
                    if hasattr(args, "items"):
                        args = dict(args)
                    yield ("function_call", {"name": fc.name, "args": args})

    # -------------------------------------------------------- groq ---
    def _groq_stream(self, messages: list[dict], declarations: list[dict], model_name: str):
        try:
            from groq import Groq
        except ImportError as e:
            raise LLMError("groq SDK not installed. Run: pip install -r requirements.txt") from e

        model_id = model_name.split("/", 1)[1] if "/" in model_name else model_name
        if self._groq_client is None:
            self._groq_client = Groq(api_key=config.GROQ_API_KEY)

        oai_messages = self._to_openai_messages(messages)
        tools = [{"type": "function", "function": d} for d in declarations] if declarations else None
        stream = self._groq_client.chat.completions.create(
            model=model_id,
            messages=oai_messages,
            tools=tools,
            stream=True,
            temperature=0.4,
        )

        pending_calls: dict[int, dict] = {}
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                yield ("text", delta.content)
            tcs = getattr(delta, "tool_calls", None)
            if tcs:
                for tc in tcs:
                    slot = pending_calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            slot["args"] += fn.arguments
        for slot in pending_calls.values():
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {"raw": slot["args"]}
            yield ("function_call", {"name": slot["name"], "args": args})

    def _to_openai_messages(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": self.system_prompt}]
        fc_counter = 0
        pending_ids: list[str] = []
        for m in messages:
            role = "assistant" if m.get("role") == "model" else "user"
            content = m.get("content", "")
            if isinstance(content, str):
                out.append({"role": role, "content": content})
                continue
            text_parts: list[str] = []
            calls: list[dict] = []
            responses: list[dict] = []
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict):
                    continue
                if "text" in part and part["text"]:
                    text_parts.append(part["text"])
                elif "function_call" in part:
                    calls.append(part["function_call"])
                elif "function_response" in part:
                    responses.append(part["function_response"])
            if calls:
                tc_list = []
                for c in calls:
                    cid = f"friday_fc_{fc_counter}"
                    fc_counter += 1
                    pending_ids.append(cid)
                    tc_list.append(
                        {
                            "id": cid,
                            "type": "function",
                            "function": {
                                "name": c.get("name", ""),
                                "arguments": json.dumps(c.get("args", {})),
                            },
                        }
                    )
                out.append(
                    {
                        "role": "assistant",
                        "content": "".join(text_parts) or None,
                        "tool_calls": tc_list,
                    }
                )
            elif text_parts:
                out.append({"role": role, "content": "".join(text_parts)})
            for r in responses:
                cid = pending_ids.pop(0) if pending_ids else f"friday_fc_{fc_counter}"
                out.append(
                    {"role": "tool", "tool_call_id": cid, "content": json.dumps(r.get("response", {}))}
                )
        return out
