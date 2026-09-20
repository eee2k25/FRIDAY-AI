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

