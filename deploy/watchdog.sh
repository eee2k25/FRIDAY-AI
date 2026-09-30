#!/usr/bin/env sh
set -eu
URL="${FRIDAY_HEALTH_URL:-http://127.0.0.1:8765/health}"
if command -v curl >/dev/null 2>&1; then curl --fail --silent --show-error --max-time 10 "$URL" >/dev/null; else python -c "import urllib.request; urllib.request.urlopen('$URL', timeout=10).read()"; fi
