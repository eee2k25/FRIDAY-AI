"""Persistent memory tools — FRIDAY remembers between sessions.

friday.py binds the FridayMemory instance via bind_memory() after creating
the registry; the tools resolve it lazily at call time.
"""
from __future__ import annotations

import config

_memory = None


def bind_memory(memory) -> None:
    """Attach the FridayMemory instance (called from friday.py at startup)."""
    global _memory
    _memory = memory


def _mem():
    if _memory is None:
        raise RuntimeError("memory not bound yet — bind_memory() must be called at startup")
    return _memory


def save_fact(key: str, value: str, source: str = "friday") -> str:
    """Store a fact for long-term memory (survives restarts)."""
    k = _mem().save_fact(key, value, source)
    return f"Remembered: {k} = {str(value)[:200]}"


def recall_fact(key: str) -> str:
    """Fetch one stored fact by key."""
    v = _mem().get_fact(key)
    if v is None:
        return f"No stored fact for {key!r}. Ask me to save it and I will."
    return f"{key} = {v}"


def list_facts() -> str:
    """List all stored facts."""
    facts = _mem().get_all_facts()
    if not facts:
        return "No facts stored yet."
    return "\n".join(f"- {k}: {str(v)[:150]}" for k, v in list(facts.items())[:50])


def search_memory(query: str) -> str:
    """Search both stored facts and conversation history for a query."""
    hits = _mem().search_history(query, limit=10)
    facts = _mem().get_all_facts()
    fact_hits = {
        k: v
        for k, v in facts.items()
        if query.lower() in k.lower() or query.lower() in str(v).lower()
    }
    parts = []
    if fact_hits:
        parts.append("FACTS:\n" + "\n".join(f"- {k}: {v}" for k, v in fact_hits.items()))
    if hits:
        parts.append(
            "CONVERSATION HITS:\n"
            + "\n".join(f"- [{h['role']}] {h['content'][:150]} ({h['timestamp']})" for h in hits)
        )
    if not parts:
        return f"Nothing in memory matches {query!r}."
    return "\n\n".join(parts)


_DECLARATIONS: list[dict] = [
    {
        "name": "save_fact",
        "description": "Store a fact in persistent memory (survives restarts). Call this whenever the Boss says 'remember ...'.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "short snake_case key, e.g. boss_name"},
                "value": {"type": "string"},
                "source": {"type": "string", "description": "'user' (default) or 'friday'"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall_fact",
        "description": "Fetch one stored fact by key.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "list_facts",
        "description": "List all stored facts.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "search_memory",
        "description": "Search persistent facts AND conversation history for a query. Use before answering personal questions.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
