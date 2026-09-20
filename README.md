# ⚡ F.R.I.D.A.Y. — v1.0

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

## Tools (47 loaded at startup)

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
│   ├── llm_engine.py      ← Gemini + Groq adapters, streaming events, fallback chain
│   ├── streaming.py       ← streaming display handler (live tail, final render, tool styles)
│   ├── agent_loop.py      ← ReAct loop (THE BRAIN)
│   ├── memory.py          ← SQLite memory (conversations/facts/tasks/tool usage)
│   └── tool_registry.py   ← dynamic loader + safe caller
├── tools\
│   ├── __init__.py
│   ├── file_tools.py · browser_tools.py · document_tools.py
│   ├── system_tools.py · code_tools.py · research_tools.py
│   ├── math_tools.py · memory_tools.py
├── memory\friday_memory.db  (auto-created)
└── logs\friday.log          (auto-created)
```

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
