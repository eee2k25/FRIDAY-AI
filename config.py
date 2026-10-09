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


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_csv(name: str, default: str) -> list[str]:
    """Read a comma-separated setting, preserving an explicitly empty value."""
    value = os.getenv(name)
    return _parse_csv(default if value is None else value)


def _get_preferred(primary: str, legacy: str, default: str) -> str:
    """Read a preferred setting, falling back only when it is absent."""
    value = os.getenv(primary)
    if value is not None:
        return value.strip()
    return _get(legacy, default) or default


def _get_preferred_csv(primary: str, legacy: str, default: str) -> list[str]:
    """Prefer the new CSV variable, even when explicitly set to an empty list."""
    if primary in os.environ:
        return _parse_csv(os.environ[primary])
    return _get_csv(legacy, default)


def _get_csv_first(*names_and_default: str) -> list[str]:
    """Read the first comma-separated setting that is present at all.

    The first *set* variable wins, even when it is set to the empty string —
    so `FRIDAY_FALLBACK_MODELS=` explicitly disables the fallback chain rather
    than falling through to the next name. Only an entirely absent (unset)
    variable falls through.
    """
    *names, default = names_and_default
    for name in names:
        val = os.getenv(name)
        if val is not None:
            return [item.strip() for item in val.split(",") if item.strip()]
    return [item.strip() for item in default.split(",") if item.strip()]


# ------------------------------------------------------------- models ---
# Defaults track currently-served model names. The old gemini-2.0-flash-exp /
# gemini-1.5-flash defaults were delisted by Google and made a fresh clone fail
# on the very first prompt. Override either value in .env.
#
# Model names may be prefixed with a provider:
#   (no prefix)   → Google Gemini        e.g. gemini-2.5-flash
#   groq/         → Groq                 e.g. groq/llama-3.3-70b-versatile
#   openrouter/   → OpenRouter           e.g. openrouter/meta-llama/llama-3.3-70b-instruct
#   together/     → Together AI          e.g. together/meta-llama/Llama-3.3-70B-Instruct-Turbo
#   ollama/       → Ollama (local/remote) e.g. ollama/llama3.2
#   deepseek/     → DeepSeek             e.g. deepseek/deepseek-chat
#   openai/       → any OpenAI-compatible host (see OPENAI_BASE_URL)
#
# FRIDAY_MODEL is provider-neutral and overrides the legacy GEMINI_MODEL name;
# GEMINI_MODEL is still honoured so existing .env files keep working.
PRIMARY_MODEL = _get("FRIDAY_MODEL") or _get("GEMINI_MODEL", "gemini-2.5-flash")
# FRIDAY_FALLBACK_MODELS likewise overrides GEMINI_FALLBACK_MODELS. Setting it
# to the empty string yields no fallback providers at all.
FALLBACK_MODELS = _get_csv_first(
    "FRIDAY_FALLBACK_MODELS",
    "GEMINI_FALLBACK_MODELS",
    "gemini-2.5-flash-lite,groq/llama-3.3-70b-versatile,ollama",
)

GEMINI_API_KEY = _get("GEMINI_API_KEY")
GROQ_API_KEY = _get("GROQ_API_KEY")
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
TOGETHER_API_KEY = _get("TOGETHER_API_KEY")
OPENAI_API_KEY = _get("OPENAI_API_KEY")
DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY")
# Any OpenAI-compatible endpoint can be used with OPENAI_BASE_URL.
OPENAI_BASE_URL = _get("OPENAI_BASE_URL", "https://api.openai.com/v1")
# Ollama is keyless. Default: the team Ollama endpoint (OpenAI-compatible /v1).
# Point OLLAMA_BASE_URL at your own host (e.g. http://127.0.0.1:11434/v1) to override.
OLLAMA_BASE_URL = _get("OLLAMA_BASE_URL", "https://turbo-space-palm-tree-7v6jr5qx5gq4fwxrg-11434.app.github.dev/v1")
OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.2")
OLLAMA_ENABLED = _get("OLLAMA_ENABLED", "True").strip().lower() in ("1", "true", "yes")
HUGGINGFACE_TOKEN = _get("HUGGINGFACE_TOKEN")

# ---------------------------------------------------------------- agent ---
USER_NAME = _get("FRIDAY_USER_NAME", "Boss")
# The release version lives in version.py so the banner, the daemon's /status
# payload and the package metadata cannot drift apart. FRIDAY_VERSION in .env
# still wins, for anyone who needs to override it.
try:
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from version import VERSION as _VERSION
except ImportError:  # pragma: no cover - only if version.py is missing
    _VERSION = "0.0.0"
FRIDAY_VERSION = _get("FRIDAY_VERSION", _VERSION)
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

# Tool filtering: only declarations relevant to the current turn are sent to
# the model. The full 108-tool declaration set costs ~8.6k tokens on EVERY
# call — more than some fallback providers allow per minute (Groq on-demand
# caps at 8k TPM), which used to 413-kill every fallback model. Core tools
# (file/web/memory/time) are always included.
TOOL_FILTER_ENABLED = _get("TOOL_FILTER", "True").strip().lower() in ("1", "true", "yes")
MAX_TOOLS_PER_CALL = int(_get("MAX_TOOLS_PER_CALL", "40"))  # 0 = send every tool

# Shell guard policy for run_command / run_powershell / run_python_code:
#   confirm (default) — ask on the terminal before a catastrophic command
#   block             — refuse it and tell the model to propose something safer
#   allow             — no guard (pre-1.2 behaviour)
SHELL_POLICY = _get("FRIDAY_SHELL_POLICY", "confirm").strip().lower()

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
