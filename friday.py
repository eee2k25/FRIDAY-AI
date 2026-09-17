"""FRIDAY v1.2 — Groq assistant (CLI). GUI is gui.py."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pyautogui
import pyttsx3
from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

pyautogui.FAILSAFE = True

VERSION = "1.2"
KEY_NAME = "GROQ_API_KEY"
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
REQUIRE_CONFIRM = os.getenv("FRIDAY_REQUIRE_CONFIRM", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MEMORY_FILE = ROOT / "memory.json"
RELEASES_API = "https://api.github.com/repos/eee2k25/FRIDAY-AI/releases/latest"
RELEASES_PAGE = "https://github.com/eee2k25/FRIDAY-AI/releases/latest"

KNOWN_APPS = {
    "word": ["cmd", "/c", "start", "", "winword"],
    "winword": ["cmd", "/c", "start", "", "winword"],
    "notepad": ["notepad"],
    "chrome": ["cmd", "/c", "start", "", "chrome"],
    "edge": ["cmd", "/c", "start", "", "msedge"],
    "browser": ["cmd", "/c", "start", "", "msedge"],
    "calculator": ["calc"],
    "calc": ["calc"],
    "explorer": ["explorer"],
}

API_KEY = (os.getenv(KEY_NAME) or "").strip()
if not API_KEY:
    print("[ERROR] GROQ_API_KEY missing. Run friday.bat so it can ask for a key.")
    sys.exit(1)

client = Groq(api_key=API_KEY)

engine = pyttsx3.init()
engine.setProperty("rate", 175)
engine.setProperty("volume", 1.0)

SYSTEM = (
    "You are FRIDAY, a helpful Windows assistant. "
    "Keep spoken replies short. Use tools only when needed. "
    "Never ask for or repeat API keys. "
    "Do not claim full admin control. "
    "If a tool is refused, explain briefly and continue."
)


def speak(text: str) -> None:
    print(f"Friday: {text}")
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass


def confirm(action: str) -> bool:
    if not REQUIRE_CONFIRM:
        return True
    try:
        ans = input(f"  Allow FRIDAY to {action}? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


def safe_path(file_path: str) -> Path:
    p = Path(file_path).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    try:
        p.relative_to(ROOT)
    except ValueError as e:
        raise PermissionError(f"Refused path outside FRIDAY folder: {p}") from e
    return p


def persistable(msgs: list) -> list:
    out = [{"role": "system", "content": SYSTEM}]
    for m in msgs:
        if isinstance(m, dict):
            role, content = m.get("role"), m.get("content")
        else:
            role, content = getattr(m, "role", None), getattr(m, "content", None)
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out[-31:]


def load_memory() -> list:
    if not MEMORY_FILE.exists():
        return [{"role": "system", "content": SYSTEM}]
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("bad memory")
        cleaned = persistable(data)
        if not cleaned or cleaned[0].get("role") != "system":
            cleaned = [{"role": "system", "content": SYSTEM}] + [
                m for m in cleaned if m.get("role") != "system"
            ]
        return cleaned
    except Exception:
        return [{"role": "system", "content": SYSTEM}]


def save_memory(msgs: list) -> None:
    try:
        MEMORY_FILE.write_text(json.dumps(persistable(msgs), indent=2), encoding="utf-8")
    except Exception:
        pass


messages: list = load_memory()

tools = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open notepad, edge, chrome, word, calculator, or explorer.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open an http(s) URL in Microsoft Edge.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_on_keyboard",
            "description": "Type text with the keyboard.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_hotkey",
            "description": "Press a safe hotkey, e.g. ctrl+c.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a text file inside the FRIDAY folder only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Run a short Python snippet after confirmation.",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
]


def execute_tool(tool_name: str, arguments: dict) -> str:
    try:
        if tool_name == "open_application":
            app = (arguments.get("app_name") or "").lower().strip()
            key = re.sub(r"[^a-z]", "", app)
            cmd = KNOWN_APPS.get(key)
            if not cmd:
                return f"Unknown app '{app}'. Try notepad, edge, chrome, word, calculator, explorer."
            subprocess.Popen(cmd)
            return f"Opened {key}."

        if tool_name == "open_url":
            url = (arguments.get("url") or "").strip()
            if not (url.startswith("https://") or url.startswith("http://")):
                return "URL must start with http:// or https://."
            subprocess.Popen(["cmd", "/c", "start", "", "msedge", url])
            return f"Opened {url} in Edge."

        if tool_name == "type_on_keyboard":
            text = arguments.get("text") or ""
            if not confirm("type on the keyboard"):
                return "User refused typing."
            time.sleep(0.4)
            pyautogui.write(text, interval=0.03)
            return "Typed text."

        if tool_name == "press_hotkey":
            keys = [str(k).lower() for k in (arguments.get("keys") or [])]
            allowed = {
                "ctrl", "alt", "shift", "tab", "enter", "esc",
                "c", "v", "x", "z", "a", "s", "win",
            }
            if not keys or any(k not in allowed for k in keys):
                return f"Hotkey not allowed: {keys}"
            if not confirm(f"press {'+'.join(keys)}"):
                return "User refused hotkey."
            time.sleep(0.3)
            pyautogui.hotkey(*keys)
            return f"Pressed {', '.join(keys)}."

        if tool_name == "write_file":
            path = safe_path(arguments.get("file_path") or "")
            content = arguments.get("content") or ""
            if path.suffix.lower() in {".exe", ".bat", ".cmd", ".ps1", ".vbs"}:
                return "Refused: that file type is not allowed."
            if not confirm(f"write file {path.name}"):
                return "User refused file write."
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Wrote {path}."

        if tool_name == "execute_python_code":
            code = arguments.get("code") or ""
            if not confirm("run Python code"):
                return "User refused code execution."
            temp_file = ROOT / "temp_script.py"
            temp_file.write_text(code, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(temp_file)],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(ROOT),
            )
            if result.returncode == 0:
                out = (result.stdout or "").strip() or "(no output)"
                return f"OK:\n{out}"
            return f"Failed:\n{(result.stderr or '').strip()}"

        return f"Unknown tool: {tool_name}"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Tool error: {e}"


def listen() -> str:
    import numpy as np
    import sounddevice as sd
    import scipy.io.wavfile as wav

    fs = 16000
    max_seconds = 8.0
    silence_seconds = 1.2
    threshold = 0.015
    block = int(0.1 * fs)
    need_silent = int(silence_seconds / 0.1)
    frames: list = []
    silent = 0
    heard = False

    print("\n[LISTENING — speak, then pause to stop]")
    with sd.InputStream(samplerate=fs, channels=1, dtype="float32", blocksize=block) as stream:
        t0 = time.time()
        while time.time() - t0 < max_seconds:
            data, _ = stream.read(block)
            frames.append(data.copy())
            vol = float(np.sqrt(np.mean(np.square(data))))
            if vol > threshold:
                heard = True
                silent = 0
            elif heard:
                silent += 1
                if silent >= need_silent:
                    break

    if not heard or not frames:
        return ""

    recording = np.concatenate(frames, axis=0)
    pcm = (np.clip(recording, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    wav.write(buf, fs, pcm)
    buf.seek(0)

    print("[Transcribing...]")
    transcript = client.audio.transcriptions.create(
        file=("audio.wav", buf.read(), "audio/wav"),
        model="whisper-large-v3-turbo",
        language="en",
    )
    return (transcript.text or "").strip()


def chat_with_friday(user_input: str) -> str:
    messages.append({"role": "user", "content": user_input})
    for _ in range(5):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.6,
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            content = msg.content or ""
            messages.append({"role": "assistant", "content": content})
            save_memory(messages)
            return content
        messages.append(msg)
        for tool_call in msg.tool_calls:
            func_args = json.loads(tool_call.function.arguments or "{}")
            print(f"[TOOL] {tool_call.function.name}")
            result = execute_tool(tool_call.function.name, func_args)
            messages.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": result}
            )
    save_memory(messages)
    return "I hit the step limit for that task."


def check_for_updates() -> None:
    try:
        import urllib.request

        req = urllib.request.Request(
            RELEASES_API, headers={"User-Agent": "FRIDAY/" + VERSION}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = str(data.get("tag_name") or "").lstrip("v")
        current = VERSION.lstrip("v")
        if latest and latest != current:
            print(f"\nNew FRIDAY {latest} is available (you have {current}).")
            print(RELEASES_PAGE)
            try:
                ans = input("Open download page? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return
            if ans in ("y", "yes"):
                import webbrowser

                webbrowser.open(RELEASES_PAGE)
    except Exception:
        pass


def main() -> None:
    check_for_updates()
    speak(f"System online. FRIDAY v{VERSION} ready.")
    print("Type a command, or press Enter to speak. Type quit to exit.")
    print(f"Model: {MODEL}")
    print("-" * 40)
    while True:
        try:
            user_input = input("\n[Enter=speak, or type]: ")
        except (EOFError, KeyboardInterrupt):
            speak("Shutting down. Goodbye!")
            break
        if user_input.strip() == "":
            try:
                user_input = listen()
                print(f"You said: {user_input}")
            except Exception as e:
                print(f"[Voice failed: {e}] Type instead.")
                continue
        low = user_input.strip().lower()
        if low in {"exit", "quit", "shut down", "shutdown"}:
            speak("Shutting down. Goodbye!")
            break
        if not user_input.strip():
            continue
        try:
            speak(chat_with_friday(user_input))
        except Exception as e:
            err = str(e)
            if "429" in err:
                speak("Groq rate limit. Wait a few seconds.")
            else:
                speak("I hit an error. Check the terminal.")
                print(err)


if __name__ == "__main__":
    main()