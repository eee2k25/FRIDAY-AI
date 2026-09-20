"""FRIDAY configuration — single source of truth for all settings.

Loads .env from the project root, exposes every setting the system uses,
and auto-creates the memory/ and logs/ directories.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is in requirements.txt; fallback keeps .env working
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- .env ---
_ENV_FILE = BASE_DIR / ".env"
if load_dotenv is not None:
    load_dotenv(_ENV_FILE)
elif _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())


def _get(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    return val if val not in (None, "") else default


# ------------------------------------------------------------- models ---
# NOTE (v1.0.1): Google has delisted the 2.0-flash-exp and 1.5-flash model
# names. The defaults below keep your spec intact; override in .env with
# current model names, e.g.  GEMINI_MODEL=gemini-2.5-flash
PRIMARY_MODEL = _get("GEMINI_MODEL", "gemini-2.0-flash-exp")
FALLBACK_MODELS = [
    m.strip()
    for m in _get("GEMINI_FALLBACK_MODELS", "gemini-1.5-flash,groq/llama-3.3-70b-versatile").split(",")
    if m.strip()
]

GEMINI_API_KEY = _get("GEMINI_API_KEY")
GROQ_API_KEY = _get("GROQ_API_KEY")
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
TOGETHER_API_KEY = _get("TOGETHER_API_KEY")
HUGGINGFACE_TOKEN = _get("HUGGINGFACE_TOKEN")

# ---------------------------------------------------------------- agent ---
USER_NAME = _get("FRIDAY_USER_NAME", "Boss")
FRIDAY_VERSION = _get("FRIDAY_VERSION", "1.0.4")
DEBUG_MODE = _get("DEBUG_MODE", "False").strip().lower() in ("1", "true", "yes")
LOG_LEVEL = _get("LOG_LEVEL", "INFO").strip().upper()

MAX_AGENT_ITERATIONS = int(_get("MAX_AGENT_ITERATIONS", "15"))
MAX_CONTEXT_TOKENS = int(_get("MAX_CONTEXT_TOKENS", "900000"))
STREAMING = _get("STREAMING", "True").strip().lower() in ("1", "true", "yes")
# Tool results fed back into the LLM context are capped here. Kept modest on
# purpose: big tool results blow through fallback-model token limits (e.g.
# Groq on-demand tier caps at 8k TPM).
MAX_TOOL_RESULT_CHARS = int(_get("MAX_TOOL_RESULT_CHARS", "12000"))
HISTORY_WINDOW = int(_get("HISTORY_WINDOW", "40"))

# ------------------------------------------------------------- paths ----
MEMORY_DB_PATH = BASE_DIR / "memory" / "friday_memory.db"
LOG_PATH = BASE_DIR / "logs" / "friday.log"
TOOLS_DIR = BASE_DIR / "tools"

# auto-create directories if missing
for _d in (MEMORY_DB_PATH.parent, LOG_PATH.parent):
    _d.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------- logging ----
# Console stays clean: logs go to logs/friday.log only. Set DEBUG_MODE=True
# (or LOG_CONSOLE=True) in .env to also mirror log lines to the terminal.
def _setup_logger() -> logging.Logger:
    _logger = logging.getLogger("friday")
    if _logger.handlers:
        return _logger
    _logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    _logger.addHandler(fh)
    console_logs = DEBUG_MODE or os.getenv("LOG_CONSOLE", "").strip().lower() in ("1", "true", "yes")
    if console_logs:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        _logger.addHandler(sh)
    return _logger


logger = _setup_logger()
