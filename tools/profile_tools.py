"""Persistent user profile tools: identity, goals, preferences and working style."""
from __future__ import annotations
from tools import memory_tools

def set_profile(key: str, value: str) -> str:
    """Remember a durable profile detail such as a goal, preference, job, or name."""
    return memory_tools.save_fact(key, value, source="profile")

def get_profile() -> str:
    """Return all durable profile details FRIDAY knows about the user."""
    facts = memory_tools._memory.get_all_facts() if memory_tools._memory else {}
    return "\n".join(f"{k}: {v}" for k,v in facts.items()) or "No profile details saved yet."

def register_tools(registry):
    registry.register_tool("set_profile", set_profile, {"name":"set_profile","description":set_profile.__doc__,"parameters":{"type":"object","properties":{"key":{"type":"string"},"value":{"type":"string"}},"required":["key","value"]}})
    registry.register_tool("get_profile", get_profile, {"name":"get_profile","description":get_profile.__doc__,"parameters":{"type":"object","properties":{}}})
