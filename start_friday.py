"""FRIDAY launcher: Groq key wizard, then CLI or GUI."""
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
    lines = ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines() if ENV_FILE.exists() else []
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
    print("  Need a FREE Groq API key (yours, not shared).")
    print("    1. Open  " + GROQ_KEYS)
    print("    2. Sign in → Create API Key")
    print("    3. Copy it (starts with gsk_)")
    print("  Saved only on THIS PC in .env")
    print()
    try:
        import webbrowser

        webbrowser.open(GROQ_KEYS)
    except Exception:
        pass
    while True:
        try:
            key = input("  Paste your Groq key, then Enter:\n  > ").strip()
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
    _load_env()
    if not _key_ok(os.getenv(KEY_NAME, "")):
        ask_for_key()
    gui = "--gui" in sys.argv
    target = ROOT / ("gui.py" if gui else "friday.py")
    if not target.exists():
        print(target.name, "not found in", ROOT)
        input("Press Enter to exit...")
        sys.exit(1)
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")