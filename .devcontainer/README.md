# Codespace lifecycle

- `devcontainer.json` — deps, the `friday` launcher, port 11434, and the boot hook.
- `start-ollama.sh` — `postStartCommand`. Runs on **every** start, including each
  resume from *stopped*, which is the only hook a container without systemd has.
  It starts a model server that was already installed here and never downloads
  one at boot; `FRIDAY_OLLAMA=on|auto|off` (default `auto`) picks the policy.

The install/run/stop logic itself lives in `../deploy/codespaces/ollama-server.sh`
so a laptop, a plain Linux box and a Codespace share one implementation.
Docs: `../CODESPACES_GUIDE.md`.
