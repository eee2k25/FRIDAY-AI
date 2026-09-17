"""FRIDAY first-run launcher. Asks for Groq key if missing, then starts friday.py."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

ENV_FILE = ROOT / ".env"
KEY_NAME = "GROQ_API_KEY"
CHAT = ROOT / "friday.py"
GROQ_KEYS = "https://console.groq.com/keys"

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
    except Exception:
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def _key_ok(k: str | None) -> bool:
    if not k:
        return False
    k = k.strip().strip('"').strip("'")
    return k.startswith("gsk_") and len(k) > 20

def _upsert_env(api_key: str) -> None:
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    out, found = [], False
    for line in lines:
        if line.strip().startswith(KEY_NAME + "="):
            out.append(f"{KEY_NAME}={api_key}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{KEY_NAME}={api_key}")
    ENV_FILE.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

def ask_for_key() -> None:
    print("=" * 60)
    print("  FRIDAY  —  first-time setup")
    print("=" * 60)
    print()
    print("  This app needs a FREE Groq API key (yours, not shared).")
    print()
    print("  How to get one:")
    print("    1. Open  " + GROQ_KEYS)
    print("    2. Sign in")
    print("    3. Create API Key")
    print("    4. Copy it  (starts with gsk_ ...)")
    print()
    print("  Saved only on THIS PC in .env  —  never uploaded to GitHub.")
    print()
    try:
        import webbrowser
        webbrowser.open(GROQ_KEYS)
        print("  (Opened the key page in your browser.)")
        print()
    except Exception:
        pass
    while True:
        try:
            key = input("  Paste your Groq key here, then Enter:\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(1)
        key = key.strip().strip('"').strip("'")
        if _key_ok(key):
            _upsert_env(key)
            os.environ[KEY_NAME] = key
            print("\n  Key saved. Starting FRIDAY...\n")
            return
        print("\n  That does not look like a Groq key (should start with gsk_).\n")

def main() -> None:
    if not CHAT.exists():
        print("friday.py not found in", ROOT)
        input("Press Enter to exit...")
        sys.exit(1)
    _load_env()
    if not _key_ok(os.getenv(KEY_NAME, "")):
        ask_for_key()
    runpy.run_path(str(CHAT), run_name="__main__")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")