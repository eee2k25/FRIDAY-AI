# ⚡ F.R.I.D.A.Y. — v1.8

**Female Replacement Intelligent Digital Agent With Yoga**

FRIDAY is the Iron Man-grade AI heavy specialist — not a chatbot, not an
assistant wrapper. She is a **fully autonomous agentic AI**: Irish wit,
combat-mode efficiency, calls you *Boss*, and runs a task until the artifact
exists — file written, report created — not until she gets stuck.

- Reads 1000-page PDFs and gives you the five lines that matter
- Runs 50-tab research and compiles a real `.docx` report
- Builds complete project documentation autonomously
- Handles multi-step engineering tasks with a ReAct loop (Reason → Act → Observe → repeat)

---

## Tech stack

| Layer      | Implementation                                              |
|------------|-------------------------------------------------------------|
| Primary LLM| Gemini 2.5 Flash (`google-genai` SDK — the official successor, streaming) |
| Fallbacks  | Gemini, Groq, OpenRouter, Together, OpenAI, or local Ollama (auto-switch on API errors) |
| Agent loop | ReAct with native function calling, max 15 iterations       |
| Memory     | SQLite (`memory/friday_memory.db`) — conversations, facts, tasks, tool usage |
| Console    | Rich — streaming output, tool-call styling, Markdown reports |
| Web        | `ddgs` (DuckDuckGo) + `requests` + BeautifulSoup4 (no Selenium, no API key) |
| Docs       | python-docx (Word) · openpyxl (Excel) · pdfplumber/PyPDF2 (PDF) |
| Math       | AST-safe calculator + sympy (equations) + pint (units)      |

> **Model-name note (refinement):** Google has delisted `gemini-2.0-flash-exp`
> and `gemini-1.5-flash`. The defaults in `config.py` keep the original spec
> intact, but you almost certainly want to set current names in `.env`:
>
> ```
> GEMINI_MODEL=gemini-2.5-flash
> GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite,groq/llama-3.3-70b-versatile
> ```
>
> Or switch at runtime with the `model <name>` console command.

---

## Setup (Linux / macOS / Codespaces) — one command

```bash
./setup.sh                    # venv + deps + .env + global `friday` command
./setup.sh --with-ollama      # also install Ollama and pull llama3.2 (no API key needed)
python friday.py --doctor     # verify the install before trusting it
```

No admin rights are used: everything lands in the checkout plus `~/.local/bin`.
If that directory is not on your `PATH`, the installer prints the exact
`export PATH=...` line to add. In a Codespace this runs automatically via the
devcontainer.

| Command | What it does |
|---|---|
| `friday` | start her from any directory |
| `python friday.py --doctor` | report Python, `.env`, active model, Ollama reachability, tool count |
| `python friday.py --version` | print the version |
| `./setup.sh --ollama-only` | (re)start Ollama after a Codespace restart |
| `./setup.sh --uninstall` | remove the global `friday` command |

> The command is lowercase `friday`. `FRIDAY` will not be found.

---

## Setup (Windows) — one command, fully automatic

Double-click **`setup.bat`** (or run `.\setup.ps1` in PowerShell). It asks for
admin permission **once**, at setup, and then does everything itself:

| Step | What setup does automatically |
|---|---|
| 🐍 Python | finds Python 3.10+ (installs it via winget if missing), creates `.venv`, installs all requirements |
| 🔑 Keys | creates `.env` from `.env.example` and prompts for your `GEMINI_API_KEY` |
| ⌨️ `friday` command | installs a global launcher on your PATH — open **any** PowerShell/CMD window, type `friday`, she starts |
| 🛡️ Admin access | registers her scheduled tasks with **highest privileges** — approved once at setup, no UAC prompts ever again |
| 🔁 Always-on | "FRIDAY AI" task starts the daemon at every logon |
| 🧹 Daily upkeep | "FRIDAY Maintenance" task checks system performance and cleans junk **every day at 10:00** (change with `-MaintenanceTime '21:30'`) |
| ✅ First pass | runs an immediate performance check + maintenance so you start clean |

```powershell
# install everything
.\setup.ps1

# options
.\setup.ps1 -NoDaemon                     # skip the always-on daemon task
.\setup.ps1 -MaintenanceTime '21:30'      # daily tune-up at 9:30 pm instead
.\setup.ps1 -Uninstall                    # remove tasks, PATH entry and the friday command
```

Then open a **new** PowerShell window anywhere and type:

```powershell
friday
```

### Day-by-day performance & maintenance

The daily task (and the chat tools) keep the PC healthy:

- `check_system_performance` — 0-100 health score: CPU, RAM, disks, temp junk, uptime, top resource hogs, recommendations
- `run_maintenance` — clears old temp files, flushes DNS cache, trims logs (`deep=true` adds Windows component-store cleanup)
- `get_maintenance_history` — day-by-day log of every run (files removed, MB freed, RAM/disk trend)
- `list_startup_programs` — find what's slowing the boot

Just ask her: *"check system performance"*, *"run a deep maintenance"*, *"show maintenance history"*.
Headless/CLI: `friday --maintain` (or `friday --maintain --deep`). Reports land in `logs/maintenance/`.

<details>
<summary><b>Manual setup (if you prefer doing it yourself)</b></summary>

```powershell
# Step 1 — create venv
python -m venv venv

# Step 2 — activate
.\venv\Scripts\Activate.ps1

# Step 3 — upgrade pip
python -m pip install --upgrade pip

# Step 4 — install requirements
pip install -r requirements.txt

# Step 5 — directories (friday.py also creates them automatically)
New-Item -ItemType Directory -Force -Path "core","tools","memory","logs"

# Step 6 — API keys
Copy-Item .env.example .env
notepad .env
# (or, if you already have .env — add any missing keys, then:)
#   GEMINI_MODEL=gemini-2.5-flash
#   GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite,groq/llama-3.3-70b-versatile

# Step 7 — run
python friday.py
```

Or just double-click **`friday.bat`**.

</details>

### API keys needed
- **`GEMINI_API_KEY`** — required for Gemini models
- **`GROQ_API_KEY`** — recommended (fallback if Gemini rate-limits)
- **No API key is required for Ollama** (`ollama/<model>`), but the Ollama service must be reachable
- The rest (`OPENROUTER`, `TOGETHER`, `HUGGINGFACE`) are reserved for future modules (JARVIS / EDITH)
### Provider credentials
- Cloud providers need their own key only when you select them (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TOGETHER_API_KEY`, or `OPENAI_API_KEY`).
- **Ollama needs no external API key**. Run an Ollama server and select a local model as described below.

---

## Tools (73 loaded at startup)

| Module | Tools |
|---|---|
| `file_tools` | read_file · write_file · list_directory · search_files · create_folder · copy_file · delete_file (confirm-gated) · get_file_info |
| `browser_tools` | web_search · fetch_webpage (text/links/raw) · search_and_fetch · read_pdf_url · read_local_pdf |
| `document_tools` | create_word_doc · read_word_doc · append_to_word_doc · create_project_report · create_excel · read_excel · append_excel_row |
| `system_tools` | run_command · **run_powershell** · run_python_script · run_python_code · open_application · get_system_info · list_running_processes · get_clipboard · set_clipboard · get_current_time · **check_own_logs** (self-diagnostics) |
| `code_tools` | analyze_code · write_and_run_code · fix_python_error · git_status · git_add_commit |
| `research_tools` | deep_research (depth 1–3, concurrent fetch) · research_and_write_report · summarize_document · compare_sources |
| `math_tools` | calculate · unit_convert · solve_equation |
| `memory_tools` | save_fact · recall_fact · list_facts · search_memory |

Every tool self-registers on import via `ToolRegistry.auto_discover()` and
returns a **string** (the LLM reads strings). Tool failures never kill the
loop — they're fed back to the model as *"try another approach"*.

---

## Usage examples

```
Boss → what time is it?
Boss → create a text file on my desktop called test.txt with today's date and hello world
Boss → search for the latest Gemini API updates and give me a summary
Boss → search for an Arduino PWM tutorial, save the best one as a Word doc in Documents
Boss → research everything about 555 timer circuits, create a complete technical
       report as a Word doc and save it to my Desktop
Boss → write a Python script that prints fibonacci to 100 and run it
Boss → my name is Tony, remember that
Boss → what's my name?
```

### Console commands
`help` · `tools` · `memory` · `status` · `clear` · `model <name>` · `exit`

---

## Cloud extensions

FRIDAY can use **Gmail, Google Drive, Google Calendar, Google Docs and GitHub**
as first-class agent tools. Extensions are optional and loaded safely even when
no account is connected. Ask `list my connections` at any time to see their
status.

### Google Workspace — one OAuth connection

1. In Google Cloud Console, enable the **Gmail, Drive, Calendar and Docs APIs**.
2. Configure the OAuth consent screen and create an OAuth Client ID with type
   **Desktop app**.
3. Download its JSON file and add its path to `.env`:

   ```env
   GOOGLE_CLIENT_SECRET_FILE=C:\path\to\client_secret.json
   ```

4. Start FRIDAY and say **“connect Google Workspace”**. Your browser asks you
   to approve the account and returns to a temporary localhost callback.

The grant adds Gmail search/read/draft/send, Drive search/upload/download,
Calendar list/create, and Docs read/create. The refresh token is stored at
`memory/connections/google_token.json`, restricted to the current OS user where
supported, and ignored by Git. Say **“disconnect Google Workspace”** to remove
FRIDAY's local token. You can revoke the grant completely from your Google
Account's third-party access page.

> Google may show an “unverified app” warning while your personal OAuth app is
> in testing. Add your Google account as a test user; never commit the client
> secret or token files.

### GitHub and local Git

Use a fine-grained GitHub token limited to only the repositories FRIDAY needs:

```env
GITHUB_TOKEN=github_pat_...
```

Alternatively, install GitHub CLI and run `gh auth login`; FRIDAY reuses that
login without copying the token into its configuration. GitHub tools can list
repositories, issues and pull requests, create issues, and read repository
files. Existing local Git tools continue to provide status and commits.

Example requests:

```text
Boss → show unread Gmail from this week
Boss → draft a reply to message 18c… (do not send it)
Boss → upload report.docx to my Drive
Boss → what's on my calendar for the next three days?
Boss → create a Google Doc called Project Brief with this outline
Boss → list open issues in owner/repository
```

---

## File structure

```
C:\MARVEL\FRIDAY\
├── friday.py              ← main entry (banner, REPL, special commands)
├── friday.bat             ← launcher
├── requirements.txt
├── config.py              ← all settings, model chain, paths, logging
├── persona.py             ← FRIDAY personality + dynamic context injection
├── .env                   ← API keys (never commit)
├── .env.example
├── selftest.py            ← offline smoke test (no API keys needed)
├── core\
│   ├── __init__.py
│   ├── llm_engine.py      ← Gemini / Groq / OpenRouter / Together / OpenAI / Ollama adapters
│   ├── streaming.py       ← streaming display handler (live tail, final render, tool styles)
│   ├── agent_loop.py      ← ReAct loop (THE BRAIN)
│   ├── memory.py          ← SQLite memory (conversations/facts/tasks/tool usage)
│   ├── tokens.py          ← context budgeting (enforces MAX_CONTEXT_TOKENS)
│   ├── office.py          ← MS Office bridge (COM automation, PDF export)
│   ├── safety.py          ← destructive-shell-command guard
│   └── tool_registry.py   ← dynamic loader + safe caller
├── tools\
│   ├── __init__.py
│   ├── file_tools.py · browser_tools.py
│   ├── word_tools.py      ← Word: tables, find/replace, images, PDF
│   ├── powerpoint_tools.py ← PowerPoint: decks from outlines, charts, notes
│   ├── excel_tools.py     ← Excel: formulas, sheets, charts, CSV, profiling
│   ├── document_tools.py  ← back-compat shim re-exporting the old names
│   ├── system_tools.py · code_tools.py · research_tools.py
│   ├── math_tools.py · memory_tools.py
├── tests\                 ← pytest suite (run: pytest)
├── pyproject.toml         ← packaging, ruff + pytest config
├── memory\friday_memory.db  (auto-created)
└── logs\friday.log          (auto-created)
```

---

## Tests & linting

```bash
pip install -e ".[dev]"
pytest              # 302 tests, no API keys and no network needed
ruff check .        # lint
```

CI runs both on every push across Python 3.10 / 3.11 / 3.12
(`.github/workflows/ci.yml`).

---

## Model providers

Any model in the chain may carry a provider prefix; cloud models whose API key
is missing are silently skipped, so you can list more than you have keys for.
Local Ollama models do not need a key.

| Prefix | Provider | Example |
|---|---|---|
| *(none)* | Google Gemini | `gemini-2.5-flash` |
| `ollama/` | Ollama (OpenAI-compatible local/remote endpoint) | `ollama/llama3.2`, `ollama/qwen2.5:7b` |
| `groq/` | Groq | `groq/llama-3.3-70b-versatile` |
| `openrouter/` | OpenRouter | `openrouter/meta-llama/llama-3.3-70b-instruct` |
| `together/` | Together AI | `together/meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| `deepseek/` | DeepSeek | `deepseek/deepseek-chat` |
| `openai/` | OpenAI-compatible endpoint | `openai/gpt-4.1-mini` |

Cloud-provider example:

```env
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=groq/llama-3.3-70b-versatile,openrouter/meta-llama/llama-3.3-70b-instruct
```

### Ollama setup (local or remote)

Install and start [Ollama](https://ollama.com/download), then pull a model. On
Windows PowerShell, open one terminal for the server and another for FRIDAY:

```powershell
ollama serve
```

```powershell
ollama pull llama3.2
```

Set these values in `.env` (remove any cloud fallbacks if you want all requests
to stay local):

```env
OLLAMA_ENABLED=True
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=llama3.2
FRIDAY_MODEL=ollama/llama3.2
FRIDAY_FALLBACK_MODELS=
```

`FRIDAY_MODEL` / `FRIDAY_FALLBACK_MODELS` are provider-neutral and override the
legacy `GEMINI_MODEL` / `GEMINI_FALLBACK_MODELS` names, which still work if you
would rather not touch an existing `.env`. An *explicitly empty*
`FRIDAY_FALLBACK_MODELS=` turns the fallback chain off; leaving the variable
unset falls through to `GEMINI_FALLBACK_MODELS` and then to the built-in
defaults.

Health checks:
- Native API: `http://<host>:11434/api/tags`
- OpenAI-compatible endpoint used by FRIDAY:
  `http://<host>:11434/v1/chat/completions`

Important deployment caveat: if Ollama runs in a different Codespace/container
from FRIDAY, `127.0.0.1` points to FRIDAY's own environment. Use a network-
reachable host/port (forwarded URL, shared container network, or run both in
the same environment).

Start FRIDAY with `python friday.py`. You should see `Model: ollama/llama3.2`
and `Fallbacks: 0`. The short form `FRIDAY_MODEL=ollama` uses `OLLAMA_MODEL`.
Ollama's OpenAI-compatible endpoint streams text and tool calls, so FRIDAY's
normal tools remain available. Tagged models work unchanged —
`ollama/deepseek-r1:7b`, `ollama/qwen2.5:7b`.

---

## Microsoft Office

Office support is **hybrid**: file-based by default (works on any OS, with or
without Office installed) plus a Windows layer that drives the real apps.

### Word — 11 tools

| Tool | What it does |
|---|---|
| `create_word_doc` | Build a .docx from markdown-lite |
| `read_word_doc` | Extract text, headings, bullets and tables |
| `append_to_word_doc` | Add more content to an existing doc |
| `create_project_report` | Title page, date, TOC, sections, page breaks |
| `add_table_to_word` | Append a real table from JSON rows |
| `add_image_to_word` | Insert a picture with an optional caption |
| `word_find_replace` | Replace across body, tables, headers **and** footers |
| `get_word_doc_info` | Word/table/image counts + heading outline |
| `word_to_pdf` | PDF via Word (COM), falling back to LibreOffice |
| `open_in_office` | Open the document in its real app |
| `office_status` | What Office integration is available on this machine |

Markdown-lite understood by every Word tool:

```
# / ## / ###     headings          **bold**     bold runs
- / *            bullets           > quote      block quote
1.               numbered list     ---          horizontal rule
| a | b |        real Word tables (needs a |---|---| separator row)
```

### PowerPoint — 9 tools

| Tool | What it does |
|---|---|
| `create_presentation` | **A whole deck from one markdown outline** |
| `add_slide` | Append a bullet or table slide |
| `add_image_slide` | Image auto-scaled to fit and centred |
| `add_table_slide` | Table slide from JSON rows |
| `add_chart_slide` | Native editable bar/column/line/pie/doughnut chart |
| `read_presentation` | Titles, bullets, tables, charts and notes as text |
| `set_speaker_notes` | Notes on any slide (1-based) |
| `get_presentation_info` | Slide inventory marking images/tables/charts/notes |
| `pptx_to_pdf` | PDF via PowerPoint (COM) or LibreOffice |

One call builds the whole deck — `# ` starts each slide, indentation sets
bullet depth, `Notes:` becomes speaker notes, and a pipe table becomes a real
PowerPoint table:

```
# Agenda
- Where we are
  - Word shipped
- What's next
Notes: keep this to 30 seconds

# Numbers
| Region | Q3  |
|---|---|
| EMEA   | 4.1M |
```

Decks default to 16:9 widescreen (`widescreen=false` for 4:3). Charts are real
PowerPoint chart objects, so the Boss can edit the data in the app.

### Excel — 13 tools

| Tool | What it does |
|---|---|
| `create_excel` | Rows → .xlsx with bold frozen header, auto-fitted columns |
| `add_excel_sheet` | Multi-sheet workbooks |
| `append_excel_row` | Append a row |
| `read_excel` | Sheet as a pipe table, formula-aware |
| `read_excel_range` | Just `A1:C10` — cheap on huge sheets |
| `update_excel_cells` | `{"B2": 42, "D10": "=SUM(D2:D9)"}` — real formulas |
| `format_excel_range` | Bold, number formats, fill colour, width |
| `add_excel_chart` | Native bar/column/line/pie/scatter charts |
| `csv_to_excel` / `excel_to_csv` | Import/export, with numeric type coercion |
| `summarize_excel` | Per-column profile: sum/mean/median/min/max or top values |
| `get_excel_info` | Sheets, formula counts, charts, freeze panes |
| `excel_to_pdf` | PDF via Excel (COM) or LibreOffice |

**The formula gotcha, handled.** openpyxl writes formulas but never evaluates
them, so a plain read returns `None` where a calculation lives. FRIDAY detects
that and shows the formula text with a note instead of reporting a blank:

```
Total | =SUM(B2:B4) | =SUM(C2:C4)

[2 formula cell(s) have no cached value yet — Excel/LibreOffice computes them
 on open. The formula text is shown instead.]
```

`summarize_excel` is the tool to reach for before answering questions about a
spreadsheet — it profiles every column instead of burning context on raw rows.

### Live app automation (Windows)

`word_to_pdf` and `open_in_office` use Microsoft Office itself through COM when
it is there. Off Windows — or with no Office — they fall back to headless
LibreOffice, and if that is missing too you get a plain, actionable message
instead of a traceback. Install the Windows extra with `pip install pywin32`.

Run `office_status` any time to see what this machine supports.

All three apps are now covered. `office_status` reports what this machine
supports; PDF export and open-in-app are the only Windows-flavoured parts, and
both fall back to LibreOffice.

---

## Safety

FRIDAY runs real shell commands, so catastrophic ones (`rm -rf /`, `mkfs`,
`shutdown`, `curl … | sh`, force-push, registry deletes) hit a guard first.
Set the policy in `.env`:

```env
FRIDAY_SHELL_POLICY=confirm   # ask on the terminal (default)
# FRIDAY_SHELL_POLICY=block   # refuse, and make her propose something safer
# FRIDAY_SHELL_POLICY=allow   # no guard
```

A blocked command comes back to the model as a normal tool failure with the
reason, so she reroutes instead of crashing. Everyday commands are never
interrupted.

---

## Offline self-test (no API keys)

```powershell
python selftest.py
```

Validates memory, tool auto-discovery, file/math tools, and the full ReAct
loop end-to-end using a mock LLM.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No usable model configured` banner | Add the selected cloud provider's key, or set `FRIDAY_MODEL=ollama/llama3.2` and start Ollama |
| Ollama connection refused | Start `ollama serve` in the same environment as FRIDAY; verify `OLLAMA_BASE_URL` points to its `/v1` endpoint |
| `404 model not found` from Gemini | Set `FRIDAY_MODEL=gemini-2.5-flash` in `.env` (delisted model name) |
| Gemini rate limits | Fallback chain auto-switches; add `GROQ_API_KEY` for resilience |
| Ollama provider fails / unreachable | Verify `ollama serve` is running, `OLLAMA_BASE_URL` is reachable from FRIDAY, and pull the model with `ollama pull <model>` |
| `413 … tokens per minute (TPM)` from Groq | Your Groq org is on the **on-demand tier (8k TPM)**. FRIDAY auto-trims the context and retries; for heavy work, stay on Gemini or upgrade Groq to Dev tier |
| `pip install ddgs` on Python 3.13 | Use `ddgs` (not `duckduckgo-search`, which is 3.12-only/deprecated) |
| Tool module warning at startup | `logs/friday.log` says which package is missing — `pip install -r requirements.txt` |
