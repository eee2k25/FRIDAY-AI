# ⚡ F.R.I.D.A.Y. — v1.4

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
| Fallbacks  | Gemini 1.5 Flash → Groq `llama-3.3-70b-versatile` (auto-switch on API errors) |
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

## Setup (Windows, PowerShell at `C:\MARVEL\FRIDAY\`)

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

### API keys needed
- **`GEMINI_API_KEY`** — required (primary model)
- **`GROQ_API_KEY`** — recommended (fallback if Gemini rate-limits)
- The rest (`OPENROUTER`, `TOGETHER`, `HUGGINGFACE`) are reserved for future modules (JARVIS / EDITH)

---

## Tools (63 loaded at startup)

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
│   ├── llm_engine.py      ← Gemini / Groq / OpenRouter / Together adapters + fallback chain
│   ├── streaming.py       ← streaming display handler (live tail, final render, tool styles)
│   ├── agent_loop.py      ← ReAct loop (THE BRAIN)
│   ├── memory.py          ← SQLite memory (conversations/facts/tasks/tool usage)
│   ├── tokens.py          ← context budgeting (enforces MAX_CONTEXT_TOKENS)
│   ├── office.py          ← MS Office bridge (COM automation, PDF export)
│   ├── safety.py          ← destructive-shell-command guard
│   └── tool_registry.py   ← dynamic loader + safe caller
├── tools\
│   ├── __init__.py
│   ├── file_tools.py · browser_tools.py · document_tools.py
│   ├── word_tools.py      ← Word: tables, find/replace, images, PDF
│   ├── powerpoint_tools.py ← PowerPoint: decks from outlines, charts, notes
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
pytest              # 102 tests, no API keys and no network needed
ruff check .        # lint
```

CI runs both on every push across Python 3.10 / 3.11 / 3.12
(`.github/workflows/ci.yml`).

---

## Model providers

Any model in the chain may carry a provider prefix; models whose API key is
missing are silently skipped, so you can list more than you have keys for.

| Prefix | Provider | Example |
|---|---|---|
| *(none)* | Google Gemini | `gemini-2.5-flash` |
| `groq/` | Groq | `groq/llama-3.3-70b-versatile` |
| `openrouter/` | OpenRouter | `openrouter/meta-llama/llama-3.3-70b-instruct` |
| `together/` | Together AI | `together/meta-llama/Llama-3.3-70B-Instruct-Turbo` |

```env
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=groq/llama-3.3-70b-versatile,openrouter/meta-llama/llama-3.3-70b-instruct
```

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

### Live app automation (Windows)

`word_to_pdf` and `open_in_office` use Microsoft Office itself through COM when
it is there. Off Windows — or with no Office — they fall back to headless
LibreOffice, and if that is missing too you get a plain, actionable message
instead of a traceback. Install the Windows extra with `pip install pywin32`.

Run `office_status` any time to see what this machine supports.

> The Excel upgrade is next: formulas, multi-sheet, cell edits, charts and CSV import.

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
| `No API keys found` banner | Fill `GEMINI_API_KEY` in `.env`, restart |
| `404 model not found` from Gemini | Set `GEMINI_MODEL=gemini-2.5-flash` in `.env` (delisted model name) |
| Gemini rate limits | Fallback chain auto-switches; add `GROQ_API_KEY` for resilience |
| `413 … tokens per minute (TPM)` from Groq | Your Groq org is on the **on-demand tier (8k TPM)**. FRIDAY auto-trims the context and retries; for heavy work, stay on Gemini or upgrade Groq to Dev tier |
| `pip install ddgs` on Python 3.13 | Use `ddgs` (not `duckduckgo-search`, which is 3.12-only/deprecated) |
| Tool module warning at startup | `logs/friday.log` says which package is missing — `pip install -r requirements.txt` |
