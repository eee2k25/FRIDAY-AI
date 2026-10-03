"""Persistent user profile and onboarding tools."""
from __future__ import annotations

from tools import memory_tools

PROFILE_FIELDS = ("name", "work", "goals", "preferences", "communication_style", "timezone")

def set_profile(key: str, value: str) -> str:
    """Remember a durable profile detail such as a goal, preference, job, or name."""
    if key.strip().lower() not in PROFILE_FIELDS:
        return f"Unknown profile field. Use one of: {', '.join(PROFILE_FIELDS)}"
    return memory_tools.save_fact(key, value, source="profile")

def get_profile() -> str:
    """Return all durable profile details FRIDAY knows about the user."""
    facts = memory_tools._memory.get_all_facts() if memory_tools._memory else {}
    return "\n".join(f"{k}: {v}" for k,v in facts.items()) or "No profile details saved yet."

def onboard_user(name: str, work: str = "", goals: str = "", preferences: str = "", communication_style: str = "", timezone: str = "") -> str:
    """Complete or update the user's profile in one guided onboarding step."""
    values = locals()
    saved = []
    for field in PROFILE_FIELDS:
        if values[field].strip():
            memory_tools.save_fact(field, values[field].strip(), source="onboarding")
            saved.append(field)
    return "Onboarding saved: " + ", ".join(saved) + ". You can update any field later with set_profile."

def register_tools(registry):
    def add(name, fn, props, req=()):
        registry.register_tool(name, fn, {"name":name,"description":fn.__doc__,"parameters":{"type":"object","properties":props,"required":list(req)}})
    add("set_profile", set_profile, {"key":{"type":"string"},"value":{"type":"string"}}, ("key","value"))
    add("get_profile", get_profile, {})
    add("onboard_user", onboard_user, {f:{"type":"string"} for f in PROFILE_FIELDS}, ("name",))
