#!/usr/bin/env bash
# Codespace/devcontainer boot hook for FRIDAY's local model server.
#
# Referenced from devcontainer.json as "postStartCommand", which is the only
# lifecycle hook that runs again on every *resume* of a stopped Codespace —
# and a container has no systemd, so nothing else would bring `ollama serve`
# back. It is a policy layer, not a supervisor: all the process work lives in
# ../deploy/codespaces/ollama-server.sh.
#
#   FRIDAY_OLLAMA=auto   (default) start if Ollama was installed here before,
#                        stay silent otherwise — never download 1.5 GB behind
#                        someone's back at boot.
#   FRIDAY_OLLAMA=on     install if needed, then start (first create pays the
#                        download; prebuilds cannot cache postStart work).
#   FRIDAY_OLLAMA=off    never touch Ollama (cloud keys only).
#
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER="$ROOT/deploy/codespaces/ollama-server.sh"
MODE="${FRIDAY_OLLAMA:-auto}"
STATE_DIR="${FRIDAY_OLLAMA_RUN_DIR:-$HOME/.local/state/friday}"
ENABLED_MARK="$STATE_DIR/enabled"

[ -f "$SERVER" ] || { echo "friday: missing $SERVER"; exit 0; }

case "$MODE" in
    off|0|false)
        echo "friday: FRIDAY_OLLAMA=$MODE — not starting a local model server."
        exit 0
        ;;
    on|1|true|install)
        bash "$SERVER" install || echo "friday: ollama install failed — see $STATE_DIR/ollama.log"
        ;;
    *)
        if [ -f "$ENABLED_MARK" ] || command -v ollama >/dev/null 2>&1; then
            bash "$SERVER" start || echo "friday: ollama did not start — see $STATE_DIR/ollama.log"
        else
            echo "friday: no local model server installed here yet."
            echo "        ./setup.sh --with-ollama   (or: bash deploy/codespaces/ollama-server.sh install)"
            echo "        then it auto-starts on every Codespace resume."
        fi
        ;;
esac
exit 0
