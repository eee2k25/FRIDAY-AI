#!/usr/bin/env bash
#
# FRIDAY AI — one-shot Linux / macOS installer.
#
# The Linux/macOS counterpart to setup.ps1. No admin rights are needed:
# everything lands in the checkout plus ~/.local/bin.
#
#   ./setup.sh                 create .venv, install deps, create .env,
#                              install the global `friday` command
#   ./setup.sh --with-ollama   additionally install Ollama and pull a model
#   ./setup.sh --ollama-only   skip the Python side, only set up Ollama
#   ./setup.sh --uninstall     remove the launcher this script created
#
set -euo pipefail

FRIDAY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${FRIDAY_BIN_DIR:-$HOME/.local/bin}"
SHIM="$BIN_DIR/friday"
VENV_DIR="$FRIDAY_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2}"
MIN_PY_MINOR=10

WITH_OLLAMA=0
OLLAMA_ONLY=0
UNINSTALL=0

if [ -t 1 ]; then
    C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_OFF=$'\033[0m'
else
    C_CYAN=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_OFF=''
fi

step() { printf '\n%s==> %s%s\n' "$C_CYAN" "$1" "$C_OFF"; }
ok()   { printf '    %s[OK]%s %s\n' "$C_GREEN" "$C_OFF" "$1"; }
warn() { printf '    %s[!]%s %s\n' "$C_YELLOW" "$C_OFF" "$1"; }
die()  { printf '    %s[x]%s %s\n' "$C_RED" "$C_OFF" "$1" >&2; exit 1; }

usage() {
    sed -n '3,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --with-ollama) WITH_OLLAMA=1 ;;
        --ollama-only) OLLAMA_ONLY=1 ;;
        --uninstall)   UNINSTALL=1 ;;
        -h|--help)     usage ;;
        *) die "unknown option: $arg (try --help)" ;;
    esac
done

# ------------------------------------------------------------- uninstall ---
if [ "$UNINSTALL" -eq 1 ]; then
    step "Removing the global 'friday' command"
    if [ -e "$SHIM" ]; then
        rm -f "$SHIM"
        ok "removed $SHIM"
    else
        ok "nothing to remove ($SHIM not present)"
    fi
    warn "the .venv and your .env were left in place — delete them manually if wanted"
    exit 0
fi

# --------------------------------------------------------------- Ollama ----
# One implementation of the Ollama lifecycle: deploy/codespaces/ollama-server.sh.
# It owns the binary check, the "address already in use" case, the background
# start, the model pull and the .env wiring — so a laptop, a plain Linux box and
# a Codespace all end up with the same server, and a Codespace gets a resume
# hook instead of a server that silently dies overnight.
OLLAMA_SETUP="$FRIDAY_DIR/deploy/codespaces/ollama-server.sh"

install_ollama() {
    step "Setting up Ollama (local model server)"
    if [ -f "$OLLAMA_SETUP" ]; then
        FRIDAY_OLLAMA_MODEL="$OLLAMA_MODEL" bash "$OLLAMA_SETUP" install
    else
        # Fallback for a checkout without the deploy/ tree (e.g. an unpacked
        # release zip): the old inline path, server started in the foreground
        # by whoever needs it.
        warn "$OLLAMA_SETUP not found — falling back to the built-in installer"
        command -v ollama >/dev/null 2>&1 || {
            command -v curl >/dev/null 2>&1 || die "curl is required to install Ollama"
            curl -fsSL https://ollama.com/install.sh | sh
        }
        ok "ollama $(command -v ollama)"
        if ! curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            warn "start the server yourself:  ollama serve"
        fi
        ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qxF "$OLLAMA_MODEL" \
            || ollama pull "$OLLAMA_MODEL"
    fi
    step "Ollama health"
    bash "$OLLAMA_SETUP" status || true
}

if [ "$OLLAMA_ONLY" -eq 1 ]; then
    install_ollama
    exit 0
fi

# --------------------------------------------------------------- Python ----
find_python() {
    local candidate minor
    for candidate in python3 python python3.13 python3.12 python3.11 python3.10; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        minor="$("$candidate" -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"
        if [ "$minor" -ge "$MIN_PY_MINOR" ] 2>/dev/null; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

step "Locating Python 3.$MIN_PY_MINOR+"
PY_BIN="$(find_python)" || die "no Python 3.$MIN_PY_MINOR+ found — install it, then re-run"
ok "$($PY_BIN --version 2>&1) at $(command -v "$PY_BIN")"

step "Creating the virtualenv"
if [ -x "$VENV_PY" ]; then
    ok ".venv already exists — reusing it"
else
    "$PY_BIN" -m venv "$VENV_DIR"
    ok "created $VENV_DIR"
fi

step "Installing dependencies"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r "$FRIDAY_DIR/requirements.txt"
ok "requirements installed"

step "Verifying the install"
"$VENV_PY" -c "import config, persona, friday" || die "import check failed — read the pip errors above"
ok "friday.py imports cleanly"

# ------------------------------------------------------------------ .env ---
step "Preparing .env"
if [ -f "$FRIDAY_DIR/.env" ]; then
    ok ".env already exists — keeping your settings"
else
    cp "$FRIDAY_DIR/.env.example" "$FRIDAY_DIR/.env"
    ok "created .env from .env.example"
    warn "edit it with:  nano $FRIDAY_DIR/.env"
fi
mkdir -p "$FRIDAY_DIR/logs" "$FRIDAY_DIR/memory"

# ------------------------------------------- global `friday` command -------
step "Installing the global 'friday' command"
mkdir -p "$BIN_DIR"
cat > "$SHIM" <<EOF
#!/usr/bin/env sh
# FRIDAY AI global launcher - generated by setup.sh
cd "$FRIDAY_DIR" || exit 1
exec "$VENV_PY" "$FRIDAY_DIR/friday.py" "\$@"
EOF
chmod +x "$SHIM"
ok "wrote $SHIM"

case ":$PATH:" in
    *":$BIN_DIR:"*) ok "$BIN_DIR is already on your PATH" ;;
    *)
        warn "$BIN_DIR is NOT on your PATH yet"
        warn "add this line to ~/.bashrc or ~/.zshrc, then open a new terminal:"
        printf '      export PATH="%s:$PATH"\n' "$BIN_DIR"
        ;;
esac

if [ "$WITH_OLLAMA" -eq 1 ]; then
    install_ollama
fi

step "Done"
ok "type 'friday' in a new terminal (or run: $VENV_PY friday.py)"
if [ "$WITH_OLLAMA" -eq 0 ]; then
    printf '    local model instead of API keys?  ./setup.sh --with-ollama\n'
fi
