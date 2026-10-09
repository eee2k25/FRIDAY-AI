"""LLM engine — provider-routed streaming with an automatic fallback chain.

- Gemini via the official `google-genai` SDK (streaming + native function calling)
- Groq via its OpenAI-compatible API (streaming + tool calls)
- OpenRouter, Together, OpenAI and local Ollama via OpenAI-compatible APIs
- Message format translation between internal, google-genai and OpenAI-style
  formats
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
        self._sdk_skipped: list[str] = []
        self._chain = self._build_chain()
        self._model_index = 0
        self._stats: dict[str, int] = {}
        self._last_error: str | None = None
        self._groq_client = None
        self._gemini_client = None
        if not self._chain:
            config.logger.error(
                "No usable model providers in .env — configure an API key "
                "(Gemini/Groq/OpenRouter/Together/OpenAI) or enable Ollama"
            )
            if self._sdk_skipped:
                config.logger.error(
                    "Provider SDK(s) missing for: %s — run: pip install -r requirements.txt",
                    ", ".join(self._sdk_skipped),
                )

    # --------------------------------------------------- chain mgmt ---
    @staticmethod
    def _normalize_model(m: str) -> str:
        """Strip whitespace/UI labels and expand the `ollama` model shorthand."""
        m = m.strip()
        m = re.sub(r"\s*[-–]\s*on[_ ]?demand$", "", m, flags=re.IGNORECASE)
        m = m.strip()
        if m.lower() in {"ollama", "ollama/"} and config.OLLAMA_MODEL:
            return f"ollama/{config.OLLAMA_MODEL.strip()}"
        return m

    @staticmethod
    def _provider_for(model: str) -> str:
        """Map a model name to its provider from the optional prefix."""
        low = model.lower()
        if low == "ollama":
            return "ollama"
        for prefix, provider in (
            ("ollama/", "ollama"),
            ("groq/", "groq"),
            ("openrouter/", "openrouter"),
            ("together/", "together"),
            ("openai/", "openai"),
            ("deepseek/", "deepseek"),
        ):
            if low.startswith(prefix):
                return provider
        return "gemini"

    @staticmethod
    def _key_for(provider: str) -> str | None:
        """API credential for a provider.

        Ollama is a local service and has no credential — it is gated by
        `OLLAMA_ENABLED` in `_provider_is_ready` instead, so this never
        invents a fake key that would be sent as a bogus Authorization header.
        """
        return {
            "gemini": config.GEMINI_API_KEY,
            "groq": config.GROQ_API_KEY,
            "openrouter": config.OPENROUTER_API_KEY,
            "together": config.TOGETHER_API_KEY,
            "openai": config.OPENAI_API_KEY,
            "deepseek": config.DEEPSEEK_API_KEY,
        }.get(provider)

    @staticmethod
    def _requires_api_key(provider: str) -> bool:
        """Ollama is a local service and does not require an API credential."""
        return provider != "ollama"

    @classmethod
    def _provider_is_ready(cls, provider: str) -> bool:
        """Can this provider serve requests: keyed (or keyless Ollama, when enabled)?"""
        if provider == "ollama":
            return bool(config.OLLAMA_ENABLED)
        return bool(cls._key_for(provider))

    @staticmethod
    def _sdk_available(provider: str) -> bool:
        """Can this provider's SDK actually be imported right now?

        A keyed model whose SDK is missing (stale venv, partial install) can
        never serve a request — checking once here keeps the chain honest and
        the failure diagnosable instead of a mid-stream ModuleNotFoundError.
        OpenRouter/Together/OpenAI/Ollama talk raw HTTP via `requests` — always
        available; Ollama is the local, keyless endpoint.
        """
        try:
            if provider == "gemini":
                from google import genai  # noqa: F401
            elif provider == "groq":
                import groq  # noqa: F401
        except ImportError:
            return False
        return True

    def _build_chain(self) -> list[tuple[str, str]]:
        """Ordered (model, provider) pairs, skipping missing credentials/SDKs.

        Ollama is local and keyless; all other providers require their API key.
        """
        chain: list[tuple[str, str]] = []
        self._sdk_skipped = []
        seen: set[str] = set()
        models = [config.PRIMARY_MODEL] + list(config.FALLBACK_MODELS)
        for m in models:
            m = self._normalize_model(m)
            if not m or m in seen:
                continue
            seen.add(m)
            provider = self._provider_for(m)
            if provider == "ollama" and not config.OLLAMA_ENABLED:
                config.logger.debug("skipping %s — Ollama is disabled", m)
                continue
            if self._requires_api_key(provider) and not self._key_for(provider):
                config.logger.debug("skipping %s — no API key for provider %s", m, provider)
            if not self._provider_is_ready(provider):
                config.logger.debug(
                    "skipping %s — provider %s is not configured/enabled", m, provider
                )
                continue
            if not self._sdk_available(provider):
                config.logger.warning(
                    "skipping %s — the %s SDK is not installed "
                    "(fix: pip install -r requirements.txt)",
                    m,
                    provider,
                )
                self._sdk_skipped.append(m)
                continue
            chain.append((m, provider))
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
    @staticmethod
    def _is_oversized_request_error(error: Exception) -> bool:
        message = str(error).lower()
        return any(
            signal in message
            for signal in (
                "http 413",
                "error code: 413",
                "request too large",
                "oversized request",
                "payload too large",
                "too many tokens",
                "context length",
                "context window",
                "prompt is too long",
                "input too long",
            )
        )

    def chat(self, messages: list[dict], declarations: list[dict]):
        """Yield ("text", str) and ("function_call", {name, args}) events.

        Falls back down the model chain automatically on API errors.
        `messages` use the internal format:
            {"role": "user"|"model", "content": str | [parts]}
        where parts are {"text": ...} / {"function_call": {name, args}} /
        {"function_response": {name, response}}.
        """
        if not self._chain:
            msg = "No usable models: configure a provider API key or select a local Ollama model."
            if self._sdk_skipped:
                msg += (
                    " SDK missing for: " + ", ".join(self._sdk_skipped)
                    + " — fix: pip install -r requirements.txt"
                )
            else:
                msg += " For example, set FRIDAY_MODEL=ollama/llama3.2 and OLLAMA_ENABLED=True in .env."
                msg += (
                    " For example, set GEMINI_MODEL=ollama/llama3.2 in .env"
                    " with OLLAMA_ENABLED=True."
                )
            raise LLMError(msg)
        errors: list[str] = []
        attempts = 0
        # Walk each configured provider at most once from a FIXED origin.
        # _model_index is the sticky "current model" (updated below so the
        # next chat() resumes at the model that last worked). Retrying the same
        # provider here is especially harmful for oversized requests (HTTP 413).
        start = self._model_index
        while attempts < len(self._chain):
            idx = (start + attempts) % len(self._chain)
            model_name, provider = self._chain[idx]
            self._model_index = idx
            self._stats[model_name] = self._stats.get(model_name, 0) + 1
            config.logger.info("model call #%d on %s", self._stats[model_name], model_name)
            try:
                if provider == "gemini":
                    yield from self._gemini_stream(messages, declarations, model_name)
                elif provider == "groq":
                    yield from self._groq_stream(messages, declarations, model_name)
                else:
                    yield from self._openai_compatible_stream(
                        messages, declarations, model_name, provider
                    )
                self._last_error = None
                return
            except Exception as e:  # noqa: BLE001 — any API failure triggers fallback
                line = f"{model_name}: {type(e).__name__}: {e}"
                self._last_error = line
                errors.append(line)
                if self._is_oversized_request_error(e):
                    message = "Request was too large; not retrying it unchanged. " + line
                    self._last_error = message
                    raise LLMError(message) from e
                config.logger.warning("model %s failed (%s) — trying next in chain", model_name, e)
                attempts += 1
        raise LLMError("All models in fallback chain failed:\n" + "\n".join(f"  - {e}" for e in errors))

    def get_model_status(self) -> dict:
        active = self._chain[self._model_index] if self._chain else ("(none)", None)
        return {
            "active_model": active[0],
            "provider": active[1],
            "chain": [m for m, _ in self._chain],
            "sdk_skipped": list(self._sdk_skipped),
            "calls": dict(self._stats),
            "last_error": self._last_error,
        }

    # ------------------------------------------------------- gemini ---
    def _get_gemini_client(self):
        if self._gemini_client is None:
            try:
                from google import genai
            except ImportError as e:
                raise LLMError(
                    "google-genai SDK not installed — every Gemini model is offline. "
                    "Fix: pip install google-genai   (or re-run setup.ps1)"
                ) from e
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
        try:
            from google.genai import types
        except ImportError as e:
            # Wrapped so a missing SDK surfaces as an actionable LLMError, not
            # a raw ModuleNotFoundError buried in the fallback-chain report.
            raise LLMError(
                "google-genai SDK not installed — every Gemini model is offline. "
                "Fix: pip install google-genai   (or re-run setup.ps1)"
            ) from e

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
        yield from self._emit_tool_calls(pending_calls)

    # -------------------------- OpenAI-compatible providers ---------------
    OPENAI_COMPATIBLE_ENDPOINTS = {
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        "together": "https://api.together.xyz/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
        "openai": f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
        "ollama": f"{config.OLLAMA_BASE_URL.rstrip('/')}/chat/completions",
    }

    @classmethod
    def _endpoint_for(cls, provider: str) -> str:
        """Resolve an OpenAI-compatible chat endpoint from a configured base URL."""
        if provider == "ollama":
            base_url = config.OLLAMA_BASE_URL.strip().rstrip("/")
            if base_url.endswith("/chat/completions"):
                return base_url
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            return f"{base_url}/chat/completions"
        return cls.OPENAI_COMPATIBLE_ENDPOINTS[provider]

    @staticmethod
    def _emit_tool_calls(pending: dict[int, dict]):
        """Turn accumulated streaming tool-call fragments into function_call events."""
        for slot in pending.values():
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {"raw": slot["args"]}
            yield ("function_call", {"name": slot["name"], "args": args})

    def _openai_compatible_stream(
        self, messages: list[dict], declarations: list[dict], model_name: str, provider: str
    ):
        """Stream from an OpenAI-compatible chat-completions endpoint.

        OpenRouter, Together and OpenAI use this adapter alongside local
        Ollama. Raw SSE over `requests` keeps the adapter dependency-free.
        """
        import requests

        url = self._endpoint_for(provider)
        model_id = model_name.split("/", 1)[1] if "/" in model_name else model_name
        if provider == "ollama" and (model_name.lower() == "ollama" or not model_id):
            model_id = config.OLLAMA_MODEL
        headers = {"Content-Type": "application/json"}
        # Ollama is local and keyless — never send it an Authorization header.
        if provider != "ollama":
            api_key = self._key_for(provider)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        if provider == "openrouter":
            headers["X-Title"] = "FRIDAY"
        payload = {
            "model": model_id,
            "messages": self._to_openai_messages(messages),
            "stream": True,
            "temperature": 0.4,
        }
        if declarations:
            payload["tools"] = [{"type": "function", "function": d} for d in declarations]

        try:
            resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=180)
        except requests.exceptions.RequestException as e:
            if provider == "ollama":
                raise LLMError(
                    f"Cannot reach Ollama at {config.OLLAMA_BASE_URL}. "
                    "Start the server with `ollama serve` and make sure that URL is "
                    "reachable from the FRIDAY process."
                ) from e
            raise

        if resp.status_code >= 400:
            response_text = str(getattr(resp, "text", ""))
            if provider == "ollama":
                lowered = response_text.lower()
                too_large = resp.status_code == 413 or any(
                    signal in lowered
                    for signal in (
                        "request too large",
                        "payload too large",
                        "too many tokens",
                        "context length",
                        "context window",
                        "prompt is too long",
                        "input too long",
                    )
                )
                if too_large:
                    raise LLMError(
                        f"Ollama rejected an oversized request (HTTP {resp.status_code}) at "
                        f"{config.OLLAMA_BASE_URL}; this is not an ordinary rate limit. "
                        f"FRIDAY will trim the request before retrying. Response: {response_text[:300]}"
                    )
                model_missing = (
                    resp.status_code == 404
                    or "model not found" in lowered
                    or "model_not_found" in lowered
                    or "no such model" in lowered
                )
                if model_missing:
                    raise LLMError(
                        f"Ollama model `{model_id}` was not found at {config.OLLAMA_BASE_URL}. "
                        f"Check `ollama list`, then run `ollama pull {model_id}`. "
                        f"Server response: {response_text[:300]}"
                    )
                raise LLMError(
                    f"Ollama HTTP {resp.status_code} at {config.OLLAMA_BASE_URL}. "
                    "Check that `ollama serve` is running and the configured URL is correct. "
                    f"Server response: {response_text[:300]}"
                if resp.status_code == 404:
                    raise LLMError(
                        f"Ollama does not have the model `{model_id}` (HTTP 404) at "
                        f"{config.OLLAMA_BASE_URL}. List what is installed with `ollama list`, "
                        f"then fetch it with `ollama pull {model_id}`."
                    )
                if resp.status_code == 413:
                    # The request itself is too big — retrying it unchanged can
                    # never succeed, so say so explicitly (this is an oversized
                    # request, NOT a rate limit) and let the agent loop shrink it.
                    raise LLMError(
                        f"Ollama rejected the request as too large (HTTP 413 payload too "
                        f"large) at {config.OLLAMA_BASE_URL}. The prompt exceeds the "
                        f"`{model_id}` context length — trim the conversation or switch to a "
                        "model with a larger context window."
                    )
                raise LLMError(
                    f"Ollama request failed (HTTP {resp.status_code}) at {config.OLLAMA_BASE_URL}. "
                    "Check that `ollama serve` is running, the URL is correct, and the model is "
                    f"available (`ollama list`, then `ollama pull {model_id}`). "
                    f"Response: {resp.text[:300]}"
                )
            if resp.status_code == 413:
                raise LLMError(
                    f"{provider} rejected the request as too large (HTTP 413 payload too "
                    f"large): {resp.text[:300]}"
                )
            raise LLMError(f"{provider} HTTP {resp.status_code}: {response_text[:300]}")

        pending: dict[int, dict] = {}
        for raw_line in resp.iter_lines(decode_unicode=True):
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8", errors="replace")
            if not raw_line or not raw_line.startswith("data:"):
                continue
            data = raw_line[5:].strip()
            if data in ("", "[DONE]"):
                if data == "[DONE]":
                    break
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            if delta.get("content"):
                yield ("text", delta["content"])
            for tc in delta.get("tool_calls") or []:
                slot = pending.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]
        yield from self._emit_tool_calls(pending)

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
