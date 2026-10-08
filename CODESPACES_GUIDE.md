# FRIDAY — Codespaces Guide (v1.8)

A Codespace is a remote Linux machine. Everything below happens in its
terminal, and `127.0.0.1` means *that* machine — not your laptop.

---

## 1. Start the Codespace

1. On the repo page: green **`<> Code`** → **Codespaces** → **Create codespace on main**
2. Wait ~60–90s. The devcontainer installs dependencies and the `friday`
   command automatically.

## 2. First-run setup (once per Codespace)

```bash
cd /workspaces/FRIDAY-AI

# one-shot installer: venv + deps + .env + global `friday` command
./setup.sh

# sanity-check the install before you trust it
python friday.py --doctor
```

`--doctor` prints your Python version, whether `.env` exists, which model
provider is active, whether local Ollama answers, and how many tools loaded.
It exits non-zero and lists every problem it finds.

## 3. Choose a brain

### Option A — local Ollama (no API key, no cost)

```bash
./setup.sh --with-ollama      # installs Ollama + pulls llama3.2 (~2 GB)
```

Or do it by hand:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve                  # leave this terminal running
# second terminal:
ollama pull llama3.2
```

> **`bind: address already in use`** on `ollama serve` is not an error — it
> means a server is *already* running on port 11434. Confirm with
> `curl http://127.0.0.1:11434/api/tags` and carry on; you do not need to
> start a second one.

Then set `.env`:

```env
OLLAMA_ENABLED=True
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=llama3.2
FRIDAY_MODEL=ollama/llama3.2
FRIDAY_FALLBACK_MODELS=
```

An **explicitly empty** `FRIDAY_FALLBACK_MODELS=` turns the fallback chain off.
Leaving the variable *unset* is different — it falls through to
`GEMINI_FALLBACK_MODELS`, then to the built-in defaults.

> **v1.8 default:** if `OLLAMA_BASE_URL` is not set, FRIDAY uses the team Ollama
> endpoint (`https://turbo-space-palm-tree-7v6jr5qx5gq4fwxrg-11434.app.github.dev/v1`)
> and tries it last in the fallback chain. The `127.0.0.1` value above is only for
> an Ollama server running **inside this Codespace**; keep it when you run it here.

### Option B — cloud API keys

Put keys in `.env` (or in repo **Settings → Secrets and variables → Codespaces**,
which is better than pasting them into a file):

```env
FRIDAY_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...
FRIDAY_FALLBACK_MODELS=groq/llama-3.3-70b-versatile,ollama/llama3.2
```

`FRIDAY_MODEL` / `FRIDAY_FALLBACK_MODELS` are provider-neutral and override the
legacy `GEMINI_MODEL` / `GEMINI_FALLBACK_MODELS` names, which still work.

## 4. Run her

```bash
friday          # the global command, works from any directory
python friday.py --doctor    # if something looks wrong
python selftest.py           # offline test suite, no API key needed
```

The banner should show `v1.8.0`, your `Model:` and `Fallbacks:` count.

> The command is lowercase **`friday`**. Typing `FRIDAY` gives
> `command not found`. If lowercase also fails, `./setup.sh` did not run or
> `~/.local/bin` is not on your PATH — the installer tells you the exact
> `export PATH=...` line to add.

---

## Everyday notes

- **Stop the Codespace** when done (`…` menu → *Stop codespace*). Free tier:
  60 h/month, 15 GB, auto-stops after 30 min idle.
- **After a restart**, `ollama serve` is *not* running. Start it again, or
  re-run `./setup.sh --ollama-only`. The pulled model survives; the server
  process does not.
- **Model downloads use Codespace disk.** CPU-only inference is slower than a
  GPU machine — `llama3.2` (3.2B, Q4_K_M) is the practical choice here.
- **Ollama on your laptop is unreachable** from a Codespace. Run both in the
  same Codespace, or point `OLLAMA_BASE_URL` at a network-reachable host.

## Useful commands

```bash
python friday.py --version     # FRIDAY AI v1.8.0
python friday.py --doctor      # full environment report
python friday.py --serve       # HTTP daemon on 127.0.0.1:8765
pytest -q                      # 335+ tests, all offline
ollama list                    # which local models are installed
curl http://127.0.0.1:11434/api/tags   # is the Ollama server up?
```

## Export your work

```bash
zip -r FRIDAY-FINAL.zip . -x ".venv/*" "__pycache__/*" ".git/*" "memory/*" ".env"
```

Then right-click the zip in the VS Code file explorer → **Download**.
