#!/usr/bin/env bash
#
# FRIDAY AI — Ollama as a background model server for GitHub Codespaces.
#
# Why this exists: a Codespace is a container with no systemd, so the
# `ollama serve` process you started yesterday is simply gone today, and the
# official installer's systemd unit is never going to start it. This script
# gives that process a lifecycle a container can actually honour:
#
#   ./deploy/codespaces/ollama-server.sh install    # binary + model + .env wiring
#   ./deploy/codespaces/ollama-server.sh start      # idempotent — safe on every resume
#   ./deploy/codespaces/ollama-server.sh status     # what is up, where, and if not: why
#   ./deploy/codespaces/ollama-server.sh test       # one real chat completion
#   ./deploy/codespaces/ollama-server.sh pull NAME  # add another model
#   ./deploy/codespaces/ollama-server.sh stop | restart | logs | watch
#   ./deploy/codespaces/ollama-server.sh autostart on   # survive a restart
#   ./deploy/codespaces/ollama-server.sh wire       # re-point .env at this server
#
# FRIDAY itself never needs a restart: point .env at
# http://127.0.0.1:11434/v1 and it talks to whatever this script is running.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRIDAY_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$FRIDAY_DIR/.env"

PORT="${FRIDAY_OLLAMA_PORT:-11434}"
BIND_ADDR="${FRIDAY_OLLAMA_BIND:-0.0.0.0}"
RUN_DIR="${FRIDAY_OLLAMA_RUN_DIR:-$HOME/.local/state/friday}"
PID_FILE="$RUN_DIR/ollama.pid"
# Touched once Ollama has been installed/started here. .devcontainer/start-ollama.sh
# reads it to decide whether a Codespace asked for a local server — so the opt-in
# is remembered across resumes without anyone re-downloading the bundle.
ENABLED_MARK="$RUN_DIR/enabled"
LOG_FILE="$RUN_DIR/ollama.log"
# $HOME is on the Codespace's persistent disk: the binary under /usr/local is
# rebuilt away on "Rebuild container", but the model blobs in here survive it.
MODEL_DIR="${OLLAMA_MODELS:-$HOME/.ollama/models}"
INSTALL_PREFIX="${FRIDAY_OLLAMA_PREFIX:-$HOME/.ollama-dist}"

env_get() {
    local key="$1" val="" line
    if [ -n "${!key:-}" ]; then printf '%s' "${!key}"; return 0; fi
    [ -f "$ENV_FILE" ] || return 1
    # Last unquoted assignment wins — mirrors how the app reads .env, so the
    # script and FRIDAY never disagree about which model is selected.
    line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null | tail -n1 || true)"
    [ -n "$line" ] || return 1
    val="${line#*=}"
    val="${val%$'\r'}"
    val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^["'\'']//' -e 's/["'\'']$//')"
    printf '%s' "$val"
}

MODEL="${FRIDAY_OLLAMA_MODEL:-$(env_get OLLAMA_MODEL || true)}"
MODEL="${MODEL:-llama3.2}"

if [ -t 1 ]; then
    C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_OFF=$'\033[0m'
else
    C_CYAN=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_OFF=''
fi

step() { printf '\n%s==> %s%s\n' "$C_CYAN" "$1" "$C_OFF"; }
ok()   { printf '  %s[OK]%s %s\n' "$C_GREEN" "$C_OFF" "$1"; }
warn() { printf '  %s[!]%s %s\n' "$C_YELLOW" "$C_OFF" "$1"; }
die()  { printf '  %s[x]%s %s\n' "$C_RED" "$C_OFF" "$1" >&2; exit 1; }
info() { printf '      %s\n' "$1"; }

# ------------------------------------------------------------------ model ---
LOCAL_URL="http://127.0.0.1:${PORT}"

in_codespace() { [ -n "${CODESPACE_NAME:-}" ]; }

port_forward_domain() {
    printf '%s' "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
}

# The forwarded URL is what a *browser or a teammate* uses. FRIDAY, running in
# the same Codespace, must keep using 127.0.0.1 — the public URL needs the
# port's visibility set to org/public, or every request 302s to github.dev.
public_url() {
    if in_codespace; then
        printf 'https://%s-%s.%s' "$CODESPACE_NAME" "$PORT" "$(port_forward_domain)"
    else
        printf '%s' ""
    fi
}

have_ollama() { command -v ollama >/dev/null 2>&1 || [ -x "$INSTALL_PREFIX/bin/ollama" ]; }
ollama_bin() {
    if command -v ollama >/dev/null 2>&1; then
        command -v ollama
    elif [ -x "$INSTALL_PREFIX/bin/ollama" ]; then
        printf '%s' "$INSTALL_PREFIX/bin/ollama"
    else
        return 1
    fi
}

api() { curl -fsS --max-time "${2:-4}" "$1" 2>/dev/null || true; }
healthy() { [ -n "$(api "http://127.0.0.1:${PORT}/api/tags")" ]; }

pid_alive() {
    [ -f "$PID_FILE" ] || return 1
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Which process actually holds the port. `setsid` forks when it is already a
# process-group leader, so $! is not always the server — and a server started by
# the installer or another terminal has no pid file at all. Ask the OS.
listener_pid() {
    local pid=""
    if command -v lsof >/dev/null 2>&1; then
        pid="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -n1 || true)"
    fi
    if [ -z "$pid" ] && command -v fuser >/dev/null 2>&1; then
        pid="$(fuser -n tcp "${PORT}" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' | head -n1 || true)"
    fi
    [ -n "$pid" ] || pid="$(pgrep -f 'ollama serve' 2>/dev/null | head -n1 || true)"
    printf '%s' "$pid"
}

# Re-point $PID_FILE at the live server and print a label for the caller.
track_pid() {
    if ! pid_alive; then
        local pid
        pid="$(listener_pid)"
        [ -n "$pid" ] && printf '%s\n' "$pid" > "$PID_FILE"
    fi
    pid_alive && printf 'pid %s' "$(cat "$PID_FILE")" || printf 'untracked (started elsewhere)'
}

# The exported environment the background server runs with. Ollama reads these
# at startup only, so changing one means: `stop` then `start`.
serve_env() {
    export OLLAMA_HOST="${BIND_ADDR}:${PORT}"
    export OLLAMA_MODELS="$MODEL_DIR"
    export OLLAMA_KEEP_ALIVE="${FRIDAY_OLLAMA_KEEP_ALIVE:-10m}"
    export OLLAMA_MAX_LOADED_MODELS="${FRIDAY_OLLAMA_MAX_LOADED:-1}"
    export OLLAMA_NUM_PARALLEL="${FRIDAY_OLLAMA_PARALLEL:-1}"
    # CORS for the Codespaces browser preview / any web client on that domain.
    export OLLAMA_ORIGINS="${OLLAMA_ORIGINS:-https://*.$(port_forward_domain),vscode-webview://*}"
}

# --------------------------------------------------------------- install ---
do_install() {
    step "Ollama binary"
    if have_ollama; then
        ok "already installed ($(ollama_bin))"
    else
        command -v curl >/dev/null 2>&1 || die "curl is required"
        # The bundle carries the CUDA/ROCm runtime even on a CPU-only box, so
        # this download is ~1.5 GB. It is once-per-container, not once-per-use.
        warn "downloading Ollama (~1.5 GB) — this is the slow step"
        local prefix=""
        if [ -w /usr/local/bin ]; then
            prefix="/usr/local"
        elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
            prefix="/usr/local"
            export OLLAMA_SUDO=1
        else
            prefix="$INSTALL_PREFIX"
        fi
        if [ "$prefix" = "/usr/local" ]; then
            info "installing to /usr/local/bin (needs sudo, lost on container rebuild)"
            # shellcheck disable=SC2086
            if [ -n "${OLLAMA_SUDO:-}" ]; then
                curl -fsSL https://ollama.com/install.sh | sudo sh
            else
                curl -fsSL https://ollama.com/install.sh | sh
            fi
        else
            info "no sudo — installing to $prefix/bin instead"
            mkdir -p "$prefix"
            curl -fsSL https://ollama.com/install.sh | env OLLAMA_INSTALL_DIR="$prefix" sh
            grep -qF "$prefix/bin" "$HOME/.bashrc" 2>/dev/null \
                || printf '\nexport PATH="%s/bin:$PATH"\n' "$prefix" >> "$HOME/.bashrc"
            export PATH="$prefix/bin:$PATH"
        fi
        hash -r
        have_ollama || die "ollama is still not on PATH after installing — add $(ollama_bin || echo "$prefix/bin") to PATH"
        ok "installed ($("$(ollama_bin)" --version 2>/dev/null | head -n1 || echo unknown))"
    fi

    step "Model directory"
    mkdir -p "$MODEL_DIR" "$RUN_DIR"
    : > "$ENABLED_MARK"
    ok "$MODEL_DIR (survives a container rebuild)"

    do_pull "$MODEL"

    # do_pull only starts a server when it actually has something to fetch, so
    # an install over an existing model would otherwise leave nothing listening
    # — the exact "it worked yesterday" state this script exists to prevent.
    do_start || warn "the server is not up yet — run: $0 start"

    if [ "${FRIDAY_OLLAMA_NO_WIRE:-0}" = "1" ]; then
        warn "skipped .env wiring (FRIDAY_OLLAMA_NO_WIRE=1)"
    else
        do_wire
    fi

    step "Next"
    info "1. python friday.py --doctor   # should list ollama as reachable"
    info "2. python friday.py            # she is now on the local model"
    if in_codespace; then
        if [ -f "$FRIDAY_DIR/.devcontainer/devcontainer.json" ]; then
            info "3. it now restarts itself on every Codespace resume (postStart hook)"
            info "   on a Codespace created before this rebuild, add: $0 autostart on"
        else
            info "3. so it survives a restart: $0 autostart on"
        fi
    fi
}

do_pull() {
    local want="${1:-$MODEL}"
    have_ollama || die "ollama not installed — run: $0 install"
    local bin; bin="$(ollama_bin)"
    step "Pulling model '$want'"
    if "$bin" list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qxF -e "$want" -e "$want:latest"; then
        ok "$want already downloaded"
        return 0
    fi
    mkdir -p "$MODEL_DIR" "$RUN_DIR"
    # Codespaces ships 32 GB of disk and no GPU; a 2 GB quantisation is fine,
    # a 40 GB one is not. Warn early instead of dying at 100%.
    local avail
    avail="$(df -P "$MODEL_DIR" 2>/dev/null | awk 'NR==2 {print int($4/1024/1024)}' || true)"
    if [ -n "$avail" ] && [ "$avail" -lt 6 ]; then
        warn "only ${avail} GB free on $MODEL_DIR — a 2 GB model plus overhead may not fit"
    fi
    # A pull needs a running server; start one quietly if nothing answers.
    local adopted=0
    if ! healthy; then
        (
            serve_env
            setsid "$bin" serve >>"$LOG_FILE" 2>&1 &
            echo $! > "$PID_FILE"
        )
        adopted=1
        if wait_ready; then track_pid >/dev/null; else warn "server did not come up — retrying the pull anyway"; fi
    fi
    if env OLLAMA_HOST="127.0.0.1:${PORT}" OLLAMA_MODELS="$MODEL_DIR" "$bin" pull "$want"; then
        ok "$want is ready"
    else
        [ "$adopted" = 1 ] && do_stop
        die "pull failed — is the model name exact? (try: ollama pull ${want}, see https://ollama.com/library)"
    fi
}

# ------------------------------------------------------------- .env wiring ---
# Replace the first match and drop later duplicates: a .env with the same key
# twice makes the reader and this script disagree about which value won.
env_upsert() {
    local key="$1" val="$2"
    [ -f "$ENV_FILE" ] || cp "$FRIDAY_DIR/.env.example" "$ENV_FILE" 2>/dev/null || : > "$ENV_FILE"
    if grep -Eq "^[[:space:]]*${key}=" "$ENV_FILE"; then
        awk -v k="$key" -v v="$val" '
            BEGIN { done = 0 }
            $0 ~ "^[ \t]*" k "=" { if (!done) { print k "=" v; done = 1 } next }
            { print }
        ' "$ENV_FILE" > "$ENV_FILE.friday-tmp" && mv "$ENV_FILE.friday-tmp" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
    fi
}

# Point FRIDAY at the server this script owns. Written to .env rather than to
# remoteEnv on purpose: .env wins over any stale default and is visible to
# `friday --doctor`, and a Codespace must never reach for a *public* forwarded
# URL when 127.0.0.1 is right there (no GitHub sign-in, no extra latency).
do_wire() {
    step "Wiring .env to this server"
    env_upsert OLLAMA_ENABLED True
    env_upsert OLLAMA_BASE_URL "http://127.0.0.1:${PORT}/v1"
    env_upsert OLLAMA_MODEL "$MODEL"
    env_upsert FRIDAY_MODEL "ollama/${MODEL}"
    # Explicitly empty, which is how this project switches the fallback chain
    # off — leaving it unset would fall through to the cloud defaults.
    env_upsert FRIDAY_FALLBACK_MODELS ""
    ok "$ENV_FILE now selects ollama/${MODEL}"
}

# ------------------------------------------------------------------ start ---
wait_ready() {
    local i
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        healthy && return 0
        sleep 1
    done
    return 1
}

do_start() {
    have_ollama || die "ollama not installed — run: $0 install"
    mkdir -p "$RUN_DIR" "$MODEL_DIR"

    if pid_alive && healthy; then
        ok "already running ($(track_pid)) on 127.0.0.1:${PORT}"
        return 0
    fi
    if healthy; then
        # Someone (the installer, an old terminal) started it — adopt it rather
        # than dying on "bind: address already in use".
        warn "a server is already listening on ${PORT} but I did not start it — adopting it"
        ok "adopted ($(track_pid))"
        return 0
    fi
    if pid_alive && ! healthy; then
        warn "stale pid $(cat "$PID_FILE") is alive but not answering — restarting"
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        sleep 1
    fi

    step "Starting ollama serve on ${BIND_ADDR}:${PORT}"
    (
        serve_env
        cd "$FRIDAY_DIR" || exit 1
        setsid "$(ollama_bin)" serve >>"$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
    )

    if wait_ready; then
        # Trust the live process list over $! — setsid may have forked.
        ok "$(track_pid) — answering on 127.0.0.1:${PORT}"
        mkdir -p "$RUN_DIR"; : > "$ENABLED_MARK"
        if in_codespace && [ "$BIND_ADDR" = "0.0.0.0" ]; then
            info "port-forwardable public URL: $(public_url)/v1"
            info "it only answers for others once visible: gh codespace ports visibility ${PORT}:org -c ${CODESPACE_NAME}"
        fi
    else
        warn "not answering yet; last log lines:"
        tail -n 8 "$LOG_FILE" 2>/dev/null | sed 's/^/      /'
        die "start failed — see $LOG_FILE"
    fi
    return 0
}

do_stop() {
    local stopped_by_me=0
    if pid_alive; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        sleep 1
        pid_alive && kill -9 "$(cat "$PID_FILE")" 2>/dev/null || true
        rm -f "$PID_FILE"
        stopped_by_me=1
    fi
    if healthy; then
        # A server started by the installer's systemd unit, another terminal,
        # or a different container user is not ours to kill silently.
        pkill -f "ollama serve" 2>/dev/null || true
        sleep 1
    fi
    if healthy; then
        warn "still answering on :${PORT} — it was started outside this script"
        info "find it with: pgrep -af 'ollama serve'   (or systemctl status ollama)"
        return 1
    fi
    [ "$stopped_by_me" = 1 ] && ok "stopped" || ok "port ${PORT} is free"
    return 0
}

do_status() {
    step "ollama"
    printf '  %-12s %s\n' "binary"    "$(ollama_bin || echo 'NOT INSTALLED')"
    printf '  %-12s %s\n' "model dir" "$MODEL_DIR"
    printf '  %-12s %s\n' "pid"       "$(pid_alive && cat "$PID_FILE" || echo '-')"
    if healthy; then
        printf '  %-12s %s\n' "endpoint"  "http://127.0.0.1:${PORT} ${C_GREEN}answering${C_OFF}"
        if [ "$BIND_ADDR" = "0.0.0.0" ]; then
            printf '  %-12s %s\n' "bound" "0.0.0.0:${PORT} ${C_GREEN}(port-forwardable)${C_OFF}"
        else
            printf '  %-12s %s\n' "bound" "127.0.0.1:${PORT} ${C_YELLOW}(this Codespace only)${C_OFF}"
        fi
    else
        printf '  %-12s %s\n' "endpoint"  "${C_RED}no answer on :${PORT} — run: $0 start${C_OFF}"
    fi
    if in_codespace; then
        printf '  %-12s %s\n' "public url" "$(public_url)/v1"
        printf '  %-12s %s\n' "visibility" "gh codespace ports visibility ${PORT}:org -c ${CODESPACE_NAME}"
    fi

    step "models"
    if healthy; then
        "$(ollama_bin)" list 2>/dev/null | sed 's/^/  /' || info "none"
        if api "http://127.0.0.1:${PORT}/api/ps" | tr -d '\n' | grep -Eq '"name"[[:space:]]*:[[:space:]]*"[^"]'; then
            info "loaded in RAM now (stay warm: OLLAMA_KEEP_ALIVE)"
        else
            info "no model loaded yet — it loads on the first request"
        fi
    else
        info "server down — nothing to list"
    fi

    step "friday wiring"
    local base; base="$(env_get OLLAMA_BASE_URL || true)"
    if [ -z "$base" ]; then
        warn "OLLAMA_BASE_URL not set in .env — FRIDAY is using its built-in default"
    elif printf '%s' "$base" | grep -q "127.0.0.1:${PORT}"; then
        ok "OLLAMA_BASE_URL=$base (this Codespace — correct)"
    else
        warn "OLLAMA_BASE_URL=$base points elsewhere"
        info "in this Codespace use: http://127.0.0.1:${PORT}/v1"
        info "a *.app.github.dev URL only works once the port is org/public"
    fi
    local fm; fm="$(env_get FRIDAY_MODEL || true)"
    case "$fm" in
        *ollama*) ok "FRIDAY_MODEL=$fm" ;;
        "")       warn "FRIDAY_MODEL unset — set FRIDAY_MODEL=ollama/${MODEL} to make Ollama primary" ;;
        *)        warn "FRIDAY_MODEL=$fm — her will try that provider first (set ollama/${MODEL} for local-only)" ;;
    esac
}

# One real chat completion: proves the model, the endpoint and the OpenAI
# compatibility layer all work, which /api/tags alone does not.
do_test() {
    have_ollama || die "ollama not installed — run: $0 install"
    healthy || die "server not answering on :${PORT} — run: $0 start"
    step "Asking $MODEL a question through $LOCAL_URL/v1"
    local out
    out="$(curl -fsS --max-time 180 "$LOCAL_URL/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: friday ok\"}],\"stream\":false}")" \
        || die "request failed — was the model pulled? ($0 pull $MODEL)"
    printf '%s' "$out" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print((d["choices"][0]["message"]["content"] or "").strip()[:200])
except Exception as e:
    sys.exit(f"unparsable reply: {e}")' 2>/dev/null \
        && ok "endpoint is working" || warn "server replied but not in the expected shape"
}

do_logs() {
    [ -f "$LOG_FILE" ] || die "no log at $LOG_FILE yet — has the server ever started here?"
    tail -n "${FRIDAY_OLLAMA_LOG_LINES:-40}" -f "$LOG_FILE"
}

# Keep the server up even if it crashes (OOM-killed by a model that was too
# big for a 2-core Codespace is the usual cause). Run it in its own terminal.
do_watch() {
    step "Watchdog — Ctrl-C stops watching, not the server"
    local every="${FRIDAY_OLLAMA_WATCH_SECONDS:-15}"
    while true; do
        if ! healthy; then
            printf '%s [%s] not answering, restarting%s\n' "$(date +%H:%M:%S)" "$C_YELLOW" "$C_OFF"
            do_start || true
        fi
        sleep "$every"
    done
}

# postStartCommand in devcontainer.json needs a container rebuild to take
# effect. This works on an existing Codespace: a guarded block in ~/.bashrc
# fires `start` (idempotent) whenever a terminal opens.
AUTOSTART_MARK="friday-ollama-autostart"

do_autostart() {
    local mode="${1:-status}"
    local rc="$HOME/.bashrc"
    local begin="# BEGIN $AUTOSTART_MARK"
    local end="# END $AUTOSTART_MARK"
    local line="bash '$SCRIPT_DIR/ollama-server.sh' start >/dev/null 2>&1 || true"
    case "$mode" in
        on)
            mkdir -p "$RUN_DIR"
            if grep -qF "$begin" "$rc" 2>/dev/null; then
                ok "already in $rc"
            else
                printf '\n%s\n%s\n%s\n' "$begin" "$line" "$end" >> "$rc"
                ok "autostart added to $rc — 'start' is idempotent, so a running server is untouched"
            fi
            do_start
            ;;
        off)
            if grep -qF "$begin" "$rc" 2>/dev/null; then
                sed -i "\|^${begin}\$|,\|^${end}\$|d" "$rc"
                ok "autostart removed from $rc"
            else
                ok "nothing to remove"
            fi
            ;;
        status)
            if grep -qF "$begin" "$rc" 2>/dev/null; then
                ok "autostart is ON ($rc)"
            else
                warn "autostart is OFF — enable with: $0 autostart on"
            fi
            ;;
        *) die "usage: $0 autostart [on|off|status]" ;;
    esac
}

cmd="${1:-status}"; shift || true
case "$cmd" in
    install)      do_install "$@" ;;
    start|up)     do_start ;;
    stop|down)    do_stop ;;
    restart)      do_stop; do_start ;;
    status)       do_status ;;
    logs)         do_logs ;;
    pull)
        # do_install also pulls the configured default, so only reach for it
        # when the binary is genuinely missing.
        if have_ollama; then
            do_pull "${1:-$MODEL}"
        else
            warn "ollama not installed — installing first"
            do_install
            do_pull "${1:-$MODEL}"
        fi
        ;;
    wire)         do_wire ;;
    url)          printf '%s\n' "${LOCAL_URL}/v1"; p="$(public_url)"; [ -n "$p" ] && printf '%s/v1\n' "$p" ;;
    test|ping)    do_test ;;
    watch)        do_watch ;;
    autostart)    do_autostart "$@" ;;
    -h|--help|help)
        sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        ;;
    *)            die "unknown command: $cmd (try --help)" ;;
esac
