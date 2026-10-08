# FRIDAY - Codespaces Guide (v1.0.4)

## Option A: Upload via Browser (NO git needed - easiest)
1. Go to github.com -> New repository -> Name: `MARVEL-FRIDAY` -> Private -> Create repository
2. On the empty repo page -> `Add file` -> `Upload files`
3. Drag & Drop ALL files from `FRIDAY-v1.0.4.zip` (extract on your phone/pc first, or upload zip and we extract in Codespace)
   - Or simpler: upload the zip itself, we'll extract in terminal
4. Commit directly to main

## Option B: Push via Git (if you have laptop for 2 mins)
```powershell
cd C:\MARVEL\FRIDAY
git init
git add .
git commit -m "FRIDAY v1.0.4"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/MARVEL-FRIDAY.git
git push -u origin main
```

---

## Start Codespace (30 seconds)
1. On your repo page: Press `,` (comma) or click green `<> Code` -> `Codespaces` -> `Create codespace on main`
2. Wait 60-90s - it auto runs `pip install -r requirements.txt` (you'll see it in terminal)
3. When done, terminal at bottom is ready.

## First Run Setup (do once per Codespace)
```bash
# 1. Create your .env (copy example)
cp .env.example .env
nano .env
# Paste your GEMINI_API_KEY and GROQ_API_KEY, press Ctrl+O, Enter, Ctrl+X

# 2. Verify
python selftest.py
# Should say: RESULT: 35 passed, 0 failed

# 3. Run FRIDAY
python friday.py
# Banner should show v1.0.4
```

## Daily Use
- Open github.com on phone/laptop -> Your repo -> `Code` -> `Codespaces` -> click your codespace -> terminal is there, FRIDAY still running
- To save hours: `...` menu in Codespace -> `Stop codespace` when done. (Free 60h/month, 15GB, stops auto after 30min idle anyway)

## Use local Ollama in this Codespace

The Codespace is a remote Linux machine. If FRIDAY runs here, installing Ollama
only on your Windows/Mac computer will **not** make `127.0.0.1` in the Codespace
reach that computer. The easiest setup is to run Ollama and FRIDAY in this same
Codespace. Its Python devcontainer does not install Ollama by default.

1. In the Codespaces terminal, install Ollama using its official Linux installer:

   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. Open a terminal and start the server:

   ```bash
   ollama serve
   ```

   Leave it running. If it reports that port `11434` is already in use, the
   installer may already have started the server.

3. Open a second terminal, download the model, and create/edit `.env`:

   ```bash
   ollama pull llama3.2
   cp .env.example .env   # only if you do not already have a .env
   nano .env
   ```

   Set the following (no Gemini/Groq key is needed):

   ```env
   OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
   OLLAMA_MODEL=llama3.2
   GEMINI_MODEL=ollama/llama3.2
   GEMINI_FALLBACK_MODELS=
   ```

4. Run `python friday.py` in that second terminal. The banner should show
   `Model: ollama/llama3.2` and `Fallbacks: 0`. Try `hi`.

Keep `OLLAMA_BASE_URL` at `127.0.0.1` when both processes are in the same
Codespace; you do not need to make Ollama's port public. The model download uses
Codespaces disk, and CPU-only inference may be slower than on a PC with a GPU.
After stopping/restarting the Codespace, start `ollama serve` again. If you want
FRIDAY in this Codespace to use Ollama in a different Codespace, use the other
server's reachable private address instead. Alternatively, run FRIDAY on your
own computer alongside the Ollama server there.

## Secrets - Better Way (so you don't paste keys every time)
In GitHub: Repo `Settings` -> `Secrets and variables` -> `Codespaces` -> `New repository secret`
- Name: `GEMINI_API_KEY` Value: your key
- Name: `GROQ_API_KEY` Value: your key
Create file `.env` once using `${GEMINI_API_KEY}` - or just set env in devcontainer.json remoteEnv.

## Download Final Zip Anytime
In Codespace terminal:
```bash
zip -r FRIDAY-FINAL.zip . -x "venv/*" "__pycache__/*" ".git/*" "memory/*"
```
Then in VS Code left file explorer -> Right click FRIDAY-FINAL.zip -> Download

