"""Optional ElevenLabs voice output. Text chat remains fully functional without it."""
from __future__ import annotations

import os
from pathlib import Path


def voice_status() -> str:
    """Show whether ElevenLabs voice output is configured."""
    if os.getenv("ELEVENLABS_API_KEY"):
        return "ElevenLabs voice configured."
    return "Voice is disabled. Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID to enable it."


def speak(text: str, output: str = "voice_output.mp3") -> str:
    """Generate spoken audio through ElevenLabs when configured."""
    key, voice = os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_VOICE_ID")
    if not key or not voice:
        return voice_status()
    try:
        import requests
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
            },
            timeout=60,
        )
        r.raise_for_status()
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return f"Voice saved to {path.resolve()}"
    except Exception as e:
        return f"Voice generation failed: {e}"


def register_tools(registry):
    for name, fn, props, req in [
        ("voice_status", voice_status, {}, []),
        ("speak", speak, {"text": {"type": "string"}, "output": {"type": "string"}}, ["text"]),
    ]:
        registry.register_tool(name, fn, {
            "name": name,
            "description": fn.__doc__,
            "parameters": {"type": "object", "properties": props, "required": req},
        })
