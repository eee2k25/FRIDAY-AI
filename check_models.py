"""Probe which Gemini models your API key can actually use.

Run it from the FRIDAY folder:

    python check_models.py            # list + live-test the candidates
    python check_models.py --all      # live-test every model the key lists
    python check_models.py gemini-3.8-flash gemini-3.5-flash-lite

For each model it does a real one-token generate call, so a model only shows
OK if it genuinely works with *your* key (listing alone is not enough — some
names list but 404 for new users).
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

KEY = os.getenv("GEMINI_API_KEY")
if not KEY:
    sys.exit("No GEMINI_API_KEY found — put it in .env or set it in the environment.")

try:
    from google import genai
except ImportError:
    sys.exit("google-genai not installed. Run: pip install -r requirements.txt")

CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.8-pro",
    "gemini-2.5-flash",        # expected: retired
    "gemini-2.5-flash-lite",   # expected: retired
    "gemini-2.0-flash",        # expected: retired
]

client = genai.Client(api_key=KEY)

args = [a for a in sys.argv[1:] if not a.startswith("-")]
list_all = "--all" in sys.argv

print("=== Models your key lists as available ===")
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

targets = args or (listed if list_all else CANDIDATES)

print("\n=== Live generate test ===")
working, dead = [], []
for name in targets:
    try:
        r = client.models.generate_content(model=name, contents="say ok")
        text = (getattr(r, "text", "") or "").strip().replace("\n", " ")[:40]
        print(f"  OK    {name}  -> {text}")
        working.append(name)
    except Exception as e:  # noqa: BLE001
        msg = str(e).replace("\n", " ")
        print(f"  FAIL  {name}  -> {msg[:160]}")
        dead.append(name)

print("\n=== Summary ===")
print("WORKING:", ", ".join(working) or "(none)")
print("DEAD   :", ", ".join(dead) or "(none)")
if working:
    primary = working[0]
    fallback = working[1] if len(working) > 1 else ""
    print("\nSuggested .env lines:")
    print(f"GEMINI_MODEL={primary}")
    if fallback:
        print(f"GEMINI_FALLBACK_MODELS={fallback}")
