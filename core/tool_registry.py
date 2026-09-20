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
import traceback

import config


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

    # ------------------------------------------------------------ api ---
    def register_tool(self, name: str, func, declaration: dict) -> None:
        if not name or not callable(func):
            raise ValueError(f"Invalid tool registration: {name!r}")
        if not isinstance(declaration, dict) or "description" not in declaration:
            declaration = {
                "name": name,
                "description": (getattr(func, "__doc__") or name).strip(),
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

    def list_tools(self) -> str:
        lines = [
            f"- {t['declaration']['name']}: {t['declaration']['description']}"
            for t in self._tools.values()
        ]
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
