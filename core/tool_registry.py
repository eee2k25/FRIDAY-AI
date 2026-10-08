"""Dynamic tool loader + safe caller.

Every tool module in tools/ exposes register_tools(registry). auto_discover()
imports each module and lets it self-register. All tools must return a STRING
(the LLM reads strings); exceptions are caught and turned into structured
failures so the agent loop can retry a different approach.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import re
import traceback

import config


class ToolRegistry:
    # Offered on every turn regardless of the request — the safety net that
    # keeps basic file/web/memory work possible even when the query matches
    # nothing else.
    CORE_TOOLS = (
        "read_file",
        "write_file",
        "list_directory",
        "search_files",
        "web_search",
        "fetch_webpage",
        "get_current_time",
        "save_fact",
        "recall_fact",
        "list_facts",
        "calculate",
        "run_python_code",
    )

    _STOPWORDS = frozenset(
        "a an and are as at be been but by can could did do does for from had has "
        "have how i if in into is it its me my not of on or should that the their "
        "them then there these this to was were what when where which who will "
        "with would you your".split()
    )

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

    # ------------------------------------------------------------ api ---
    def register_tool(self, name: str, func, declaration: dict) -> None:
        if not name or not callable(func):
            raise ValueError(f"Invalid tool registration: {name!r}")
        if not isinstance(declaration, dict) or "description" not in declaration:
            declaration = {
                "name": name,
                "description": (func.__doc__ or name).strip(),
                "parameters": {"type": "object", "properties": {}},
            }
        declaration["name"] = name
        self._tools[name] = {"function": func, "declaration": declaration}
        config.logger.debug("tool registered: %s", name)

    @property
    def tools(self) -> dict[str, dict]:
        return dict(self._tools)

    def get_declarations(self) -> list[dict]:
        """Plain JSON-schema declarations (Gemini format)."""
        return [t["declaration"] for t in self._tools.values()]

    # ------------------------------------------------- tool filtering ---
    @staticmethod
    def _stem(word: str) -> str:
        """Naive singular: 'files'→'file', 'spreadsheets'→'spreadsheet'."""
        return word[:-1] if word.endswith("s") and len(word) > 4 else word

    @classmethod
    def _words(cls, text: str) -> set[str]:
        """Significant lowercase tokens of a text (stopwords and noise removed)."""
        return {
            cls._stem(w)
            for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) >= 3 and w not in cls._STOPWORDS
        }

    def _tool_score(self, declaration: dict, query_words: set[str], query: str) -> int:
        """Relevance of one tool to the query: name hits weigh 3x description hits."""
        name = declaration.get("name", "")
        score = 0
        if name and name in query.lower():
            score += 5  # the user literally typed the tool name
        name_words = {self._stem(w) for w in name.lower().split("_") if len(w) >= 3}
        desc_words = self._words(declaration.get("description", ""))
        score += 3 * len(query_words & name_words)
        score += len(query_words & desc_words)
        return score

    def select_declarations(
        self,
        query: str = "",
        cap: int = 40,
        extra_names=(),
        pool: list[dict] | None = None,
    ) -> list[dict]:
        """Declarations for the tools most relevant to `query`.

        Sending all 108 declarations costs ~8.6k tokens on every call — enough
        to blow past weak fallback providers' per-minute limits (Groq
        on-demand: 8k TPM) before the conversation even starts. CORE_TOOLS
        and `extra_names` (tools already used in this session) are always
        included; the rest are ranked by keyword overlap with the query.
        `cap <= 0` disables filtering and returns the whole pool.
        """
        pool = pool if pool is not None else self.get_declarations()
        if cap <= 0 or not pool:
            return list(pool)
        by_name = {d.get("name", ""): d for d in pool}
        chosen: list[str] = []

        def _add(n: str) -> None:
            if n in by_name and n not in chosen:
                chosen.append(n)

        for n in self.CORE_TOOLS:
            _add(n)
        for n in extra_names:
            _add(n)
        words = self._words(query)
        if words:
            scored = sorted(
                ((self._tool_score(d, words, query), d.get("name", "")) for d in pool),
                key=lambda t: (-t[0], t[1]),
            )
            for score, name in scored:
                if score <= 0 or len(chosen) >= cap:
                    break
                _add(name)
        return [by_name[n] for n in chosen[:cap]]

    def get_gemini_tools(self) -> list[dict] | None:
        """Wrapped form accepted by the google-generativeai SDK."""
        decls = self.get_declarations()
        return [{"function_declarations": decls}] if decls else None

    def execute_tool(self, name: str, args_dict: dict) -> dict:
        """Run a tool. Returns {success, result, error} — never raises."""
        tool = self._tools.get(name)
        if tool is None:
            known = ", ".join(sorted(self._tools))
            return {
                "success": False,
                "result": "",
                "error": f"Unknown tool '{name}'. Available tools: {known}",
            }
        args = args_dict if isinstance(args_dict, dict) else {}
        try:
            result = tool["function"](**args)
        except TypeError as e:
            return {
                "success": False,
                "result": "",
                "error": f"Argument error for {name}: {e}",
            }
        except Exception as e:
            config.logger.error("tool %s failed: %s\n%s", name, e, traceback.format_exc(limit=3))
            return {"success": False, "result": "", "error": f"{type(e).__name__}: {e}"}
        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False, indent=2, default=str)
            except (TypeError, ValueError):
                result = str(result)
        cap = config.MAX_TOOL_RESULT_CHARS
        if len(result) > cap:
            result = result[:cap] + f"\n... [truncated, {len(result)} chars total]"
        return {"success": True, "result": result, "error": None}

    def list_tools(self, compact: bool = False) -> str:
        """Human-readable tool list.

        compact=True keeps one short line per tool — used for the system
        prompt, where every tool is ALSO sent as a structured declaration and
        the full text would just double the token bill (~3k tokens).
        """
        lines = []
        for t in self._tools.values():
            d = t["declaration"]
            desc = " ".join(str(d.get("description", "")).split())
            if compact:
                desc = desc[:60].rstrip() + ("…" if len(desc) > 60 else "")
            lines.append(f"- {d['name']}: {desc}")
        return "\n".join(lines) if lines else "(no tools loaded)"

    def auto_discover(self, package_name: str = "tools") -> dict:
        """Import every module in the tools package; each self-registers."""
        try:
            package = importlib.import_module(package_name)
        except ImportError as e:
            return {"loaded": 0, "errors": [f"cannot import package {package_name}: {e}"]}
        loaded, errors = 0, []
        for mod_info in pkgutil.iter_modules(package.__path__):
            if mod_info.name.startswith("_"):
                continue
            full = f"{package_name}.{mod_info.name}"
            try:
                module = importlib.import_module(full)
                register = getattr(module, "register_tools", None)
                if callable(register):
                    register(self)
                    loaded += 1
            except Exception as e:
                errors.append(f"{full}: {type(e).__name__}: {e}")
                config.logger.warning("tool module %s failed to load: %s", full, e)
        return {"loaded": loaded, "errors": errors}
