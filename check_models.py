"""Probe which models your API keys can actually use.

Run it from the FRIDAY folder:

    python check_models.py                 # test whichever providers have keys
    python check_models.py --groq          # Groq only
    python check_models.py --gemini        # Gemini only
    python check_models.py --all           # test every model the keys list
    python check_models.py groq/openai/gpt-oss-120b gemini-3.8-flash

Each candidate gets a real one-token completion, so a model is only reported
OK if it genuinely works with *your* key — listing alone is not enough, some
names list fine and then 404 or 403 on use.
"""
from __future__ import annotations

import os
import sys

# Load .env the same way config.py does, without importing the whole app.
_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV):
    for _line in open(_ENV, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

flags = {a for a in sys.argv[1:] if a.startswith("--")}
explicit = [a for a in sys.argv[1:] if not a.startswith("-")]
list_all = "--all" in flags
only_groq = "--groq" in flags
only_gemini = "--gemini" in flags

GEMINI_CANDIDATES = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.8-pro"]
# Verified against a live Groq key (Oct 2026). The llama-3.x ids Groq used to
# serve are gone from new accounts, so they are not probed by default — pass
# them on the command line if your account still has them.
GROQ_CANDIDATES = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-safeguard-20b",
    "qwen/qwen3.8-27b",
    "allam-2-7b",
]

working: list[str] = []
dead: list[str] = []


# ----------------------------------------------------------------- groq ---
def check_groq() -> None:
    if not GROQ_KEY:
        print("No GROQ_API_KEY in .env — skipping Groq.\n")
        return
    try:
        from groq import Groq
    except ImportError:
        print("groq SDK not installed. Run: pip install groq\n")
        return

    client = Groq(api_key=GROQ_KEY)

    print("=== Groq: models your key lists ===")
    listed: list[str] = []
    try:
        for m in client.models.list().data:
            mid = m.id
            listed.append(mid)
            ctx = getattr(m, "context_window", "") or ""
            print(f"  {mid}  (ctx {ctx})")
    except Exception as e:  # noqa: BLE001
        print(f"  (listing failed: {e})")

    targets = [m.removeprefix("groq/") for m in explicit if m.startswith("groq/")]
    if not targets:
        targets = listed if list_all else [m for m in GROQ_CANDIDATES if not listed or m in listed]

    print("\n=== Groq: live completion test ===")
    for name in targets:
        try:
            r = client.chat.completions.create(
                model=name,
                messages=[{"role": "user", "content": "say ok"}],
                max_tokens=64,
            )
            text = (r.choices[0].message.content or "").strip().replace("\n", " ")[:40]
            print(f"  OK    groq/{name}  -> {text}")
            working.append(f"groq/{name}")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  groq/{name}  -> {str(e).replace(chr(10), ' ')[:150]}")
            dead.append(f"groq/{name}")
    print()


# --------------------------------------------------------------- gemini ---
def check_gemini() -> None:
    if not GEMINI_KEY:
        print("No GEMINI_API_KEY in .env — skipping Gemini.\n")
        return
    if not GEMINI_KEY.startswith("AIza"):
        print(
            f"GEMINI_API_KEY looks wrong (starts with '{GEMINI_KEY[:4]}…'). "
            "A real Gemini API key starts with 'AIza' — get one at "
            "https://aistudio.google.com/apikey\n"
        )
    try:
        from google import genai
    except ImportError:
        print("google-genai not installed. Run: pip install google-genai\n")
        return

    client = genai.Client(api_key=GEMINI_KEY)

    print("=== Gemini: models your key lists ===")
    listed: list[str] = []
    try:
        for m in client.models.list():
            name = m.name.removeprefix("models/")
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                listed.append(name)
                print(f"  {name}")
    except Exception as e:  # noqa: BLE001
        print(f"  (listing failed: {e})")

    targets = [m for m in explicit if not m.startswith("groq/")]
    if not targets:
        targets = listed if list_all else GEMINI_CANDIDATES

    print("\n=== Gemini: live generate test ===")
    for name in targets:
        try:
            r = client.models.generate_content(model=name, contents="say ok")
            text = (getattr(r, "text", "") or "").strip().replace("\n", " ")[:40]
            print(f"  OK    {name}  -> {text}")
            working.append(name)
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {name}  -> {str(e).replace(chr(10), ' ')[:150]}")
            dead.append(name)
    print()


if not only_gemini:
    check_groq()
if not only_groq:
    check_gemini()

print("=== Summary ===")
print("WORKING:", ", ".join(working) or "(none)")
print("DEAD   :", ", ".join(dead) or "(none)")
if working:
    print("\nSuggested .env lines:")
    print(f"GEMINI_MODEL={working[0]}")
    if len(working) > 1:
        print("GEMINI_FALLBACK_MODELS=" + ",".join(working[1:3]))
else:
    print("\nNothing worked — check the keys in .env.")
