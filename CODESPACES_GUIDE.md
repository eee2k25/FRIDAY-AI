# FRIDAY — Codespaces Guide (v1.8)

A Codespace is a remote Linux **container**, not a VM you own. Two consequences
run through this whole page:

1. `127.0.0.1` means *that container* — never your laptop.
2. There is **no systemd**, so a background process you started yesterday is
   gone today. Anything meant to "always run" has to be started by a hook.

That second point is why an Ollama setup seems to break on its own: `ollama
serve` worked, you stopped the Codespace, and it came back dead.

---

## TL;DR — local model, no API keys

```bash
cd /workspaces/FRIDAY-AI

bash deploy/codespaces/ollama-server.sh install   # Ollama + llama3.2 + .env wiring
bash deploy/codespaces/ollama-server.sh status    # server, models, and what .env says
friday                                            # banner should read: Model: ollama/llama3.2
```

`install` ends by rewriting four keys in `.env` for you
(`OLLAMA_ENABLED`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `FRIDAY_MODEL`), so there
is no manual editing step. It never touches a key you already set.

---

## 1. Create the Codespace

On the repo page: green **`<> Code`** → **Codespaces** → **Create codespace on main**.
The devcontainer installs Python deps and the `friday` command automatically
(~60–90 s). Ollama is deliberately *not* in that path: its bundle is ~1.5 GB on
top of a ~2 GB model, and nobody should pay that on every create.

## 2. Verify the checkout

```bash
python selftest.py            # offline suite
python friday.py --doctor     # environment report: python, .env, provider chain,
                              # Ollama reachability, tool count — and fixes for it
```

`--doctor` exits non-zero and lists every problem it finds. When Ollama is
unreachable inside a Codespace it also prints the exact command to start the
server, and — if your `OLLAMA_BASE_URL` points at a `*.app.github.dev` URL — it
tells you that `http://127.0.0.1:11434/v1` is the value you want.

## 3. The model server

Everything below is one script, and it is safe to re-run at any time:

| Command | What it does |
|---|---|
| `install` | Install the binary if missing, start the server, pull `$OLLAMA_MODEL`, wire `.env` |
| `start` | Start the server (idempotent — adopts one that is already listening) |
| `stop` / `restart` | Stop / restart it |
| `status` | Binary, pid, port, binding, models, and your `.env` wiring |
| `test` | One real chat completion through `/v1/chat/completions` |
| `logs` | `tail -f` the server log |
| `pull NAME` | Add another model |
| `autostart on` | Start the server whenever a terminal opens |
| `watch` | Restart it if it dies (run in a spare terminal) |
| `url` | Print the local and the forwarded URL |

### Where things live

| Path | Notes |
|---|---|
| `~/.local/state/friday/ollama.log` | server log — read this first when it misbehaves |
| `~/.local/state/friday/ollama.pid` | the pid `stop` uses |
| `~/.ollama/models` | model blobs. `$HOME` is on the Codespace's persistent disk, so **a "Rebuild container" keeps the models** but not `/usr/local/bin/ollama` — you re-run `install` and it skips the download |

### Keeping it up automatically

`.devcontainer/devcontainer.json` runs `bash .devcontainer/start-ollama.sh` as
its `postStartCommand`, which fires on **every** start, including every resume
from *stopped*. That hook is a policy layer, not a supervisor:

- `FRIDAY_OLLAMA=auto` (default) — start the server if it was installed here
  before; otherwise print one line and do nothing. **Never downloads at boot.**
- `FRIDAY_OLLAMA=on` — install if needed, then start. Set it as a Codespace
  secret/variable to get a zero-command setup on a fresh Codespace.
- `FRIDAY_OLLAMA=off` — never touch Ollama (cloud keys only).

Two caveats worth knowing:

- A devcontainer.json change only applies after **Rebuild container**. On a
  Codespace you already have, use `autostart on` instead — it appends one
  guarded line to `~/.bashrc`, and `start` is idempotent so opening a terminal
  can never double-start the server.
- `postStart` is not captured by a prebuild, so the first-ever install is
  always paid at first use.

### Model choice on a 2-core container

Codespaces has **no GPU**, and the free machine is 2 cores / 8 GB / 32 GB disk.
A model that does not fit is OOM-killed, and the symptom is FRIDAY going silent
rather than a clean error.

| Model | Download | Good for |
|---|---|---|
| `llama3.2` (default) | ~2.0 GB | the balance point here; tool-calling works |
| `llama3.2:1b` | ~1.3 GB | snappy demos, weaker reasoning |
| `qwen2.5:3b` | ~1.9 GB | good multilingual, decent tools |
| `deepseek-r1:7b` | ~4.7 GB | reasoning-heavy, slow on CPU |
| anything ≥13B | 8 GB+ | don't — it will not stay resident |

```bash
bash deploy/codespaces/ollama-server.sh pull qwen2.5:3b
```

The pull starts a server itself if none is running, and `.env` keeps pointing at
whatever model `OLLAMA_MODEL` names.

## 4. Reaching the server from outside the Codespace

Ollama binds `0.0.0.0:11434` here because the Codespace proxy can only forward a
port that is not loopback-only. The forwarded URL is derived from the container's
own environment — nothing to paste, nothing to rot:

```
https://${CODESPACE_NAME}-11434.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}
```

`bash deploy/codespaces/ollama-server.sh url` prints it. **FRIDAY should not use
that URL from inside the same Codespace**: it round-trips GitHub's proxy and,
while the port is `private`, every request comes back as a 302 to a GitHub
sign-in page. `http://127.0.0.1:11434/v1` is correct and faster.

To let a browser preview or a teammate use it, choose the visibility:

```bash
gh codespace ports visibility 11434:org    -c "$CODESPACE_NAME"   # org members
gh codespace ports visibility 11434:public -c "$CODESPACE_NAME"   # anyone with the URL
```

`public` means exactly that: **no key, no auth, free-tier CPU burn from whoever
finds the link**. Ollama has no authentication at all. Prefer `org`, prefer
`private` when nobody else needs it, and never expose it on a machine that also
has real API keys in its environment.

## 5. Cloud providers instead (or as fallbacks)

Put keys in `.env`, or better in repo **Settings → Secrets and variables →
Codespaces**:

```env
FRIDAY_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...
FRIDAY_FALLBACK_MODELS=groq/llama-3.3-70b-versatile,ollama/llama3.2
```

`FRIDAY_MODEL` / `FRIDAY_FALLBACK_MODELS` are provider-neutral and override the
legacy `GEMINI_MODEL` / `GEMINI_FALLBACK_MODELS` names. An **explicitly empty**
`FRIDAY_FALLBACK_MODELS=` switches the chain off; leaving it unset falls through
to the legacy name and then to the built-in defaults.

## 6. Run her

```bash
friday                       # global command, works from any directory
python friday.py --serve     # HTTP daemon on 127.0.0.1:8765
pytest -q                    # 335+ tests, all offline
```

The banner shows `v1.8.0`, `Model:` and `Fallbacks:`. The command is lowercase
`friday` — `FRIDAY` is `command not found`. If lowercase also fails, `./setup.sh`
did not run or `~/.local/bin` is not on `PATH`.

## Everyday notes

- **Stop it when done** (`…` menu → *Stop codespace*). The free plan's monthly
  core-hours are consumed by a running Codespace whether or not a tab is open;
  auto-stop after 30 min idle is your friend.
- **After a restart** the server is stopped again unless an autostart hook is in
  place. The pulled model survives; the process does not.
- **`bind: address already in use`** is not an error here — it means a server is
  already on 11434. `status` shows it; `start` adopts it.
- **Ollama on your laptop is unreachable from a Codespace.** Run both in the same
  Codespace, or point `OLLAMA_BASE_URL` at a host that is genuinely on the network.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Cannot reach Ollama at http://127.0.0.1:11434/v1` | server not running → `.../ollama-server.sh start` |
| Same error, but `status` says it is answering | `.env` has a stale/foreign `OLLAMA_BASE_URL` → `.../ollama-server.sh wire` |
| 302 / HTML instead of JSON from a `.app.github.dev` URL | port visibility is `private` → `gh codespace ports visibility 11434:org` |
| `model 'x' was not found` | `.../ollama-server.sh pull x`, or set `OLLAMA_MODEL` to a name in `ollama list` |
| First reply takes minutes | CPU inference + model loading from cold. Normal-ish; keep it warm with `FRIDAY_OLLAMA_KEEP_ALIVE` |
| Replies stop mid-sentence | the model was OOM-killed → smaller model, `MAX_CONTEXT_TOKENS` down |
| `disk quota exceeded` during a pull | 32 GB fills fast → `ollama rm <unused>`, check `df -h ~` |
| Works today, dead tomorrow | no autostart → `.../ollama-server.sh autostart on` |

## Export your work

```bash
zip -r FRIDAY-FINAL.zip . -x ".venv/*" "__pycache__/*" ".git/*" "memory/*" ".env"
```

Right-click the zip in the file explorer → **Download**. Never download `.env`
into a shared folder: it holds your keys.
