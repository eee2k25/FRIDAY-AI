"""FRIDAY — main entry point.

The Iron Man-grade heavy specialist: reads a 1000-page PDF and gives you the
five lines that matter. Runs until the task is DONE, not until she gets stuck.
"""
from __future__ import annotations

import sys
import uuid
import warnings

# Keep the console a clean chat surface — no library warnings to stderr.
warnings.filterwarnings("ignore")

from rich import box
from rich.console import Console
from rich.panel import Panel

import config
from core.agent_loop import AgentLoop
from core.llm_engine import LLMEngine
from core.memory import FridayMemory
from core.tool_registry import ToolRegistry

BANNER = r"""
  ██████╗██████╗  ██████╗ ████████╗███████╗
 ██╔════╝██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝
 ██║     ██████╔╝██║   ██║   ██║   ███████╗
 ██║     ██╔══██╗██║   ██║   ██║   ╚════██║
 ╚██████╗██║  ██║╚██████╔╝   ██║   ███████║
  ╚═════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚══════╝"""

_HELP = (
    "help          — this list\n"
    "tools         — list all loaded tools\n"
    "memory        — memory summary (facts, tasks, tool usage)\n"
    "status        — active model, fallback chain, call stats\n"
    "clear         — wipe this session's conversation (facts kept)\n"
    "model <name>  — switch primary model at runtime\n"
    "exit          — shut down"
)


def _banner(console: Console, tool_count: int, status: dict) -> None:
    body = (
        f"[bold]⚡ F.R.I.D.A.Y[/bold]  v{config.FRIDAY_VERSION}\n"
        f"Female Replacement Intelligent Digital Agent With Yoga\n"
        f"Model: [cyan]{status['active_model']}[/cyan] | Fallbacks: {max(0, len(status['chain']) - 1)} "
        f"| Tools: [cyan]{tool_count}[/cyan]\n"
        f"Status: [green bold]ONLINE[/green bold] — built for {config.USER_NAME}"
    )
    console.print(BANNER)
    console.print(Panel(body, box=box.DOUBLE_EDGE, border_style="cyan", width=70))


def _sdk_problems() -> list[str]:
    """Actionable boot warnings when a provider's Python SDK is missing.

    A stale virtualenv (installed before a requirements change) is the classic
    cause of 'every model in the chain failed' — surface it at startup with
    the exact fix instead of letting it detonate mid-conversation.
    """
    problems = []
    if config.GEMINI_API_KEY:
        try:
            from google import genai  # noqa: F401
        except ImportError:
            problems.append(
                "google-genai SDK missing — all Gemini models are OFFLINE. "
                "Fix: .venv\\Scripts\\pip install google-genai   (or re-run setup.ps1)"
            )
    if config.GROQ_API_KEY:
        try:
            import groq  # noqa: F401
        except ImportError:
            problems.append(
                "groq SDK missing — all Groq models are OFFLINE. "
                "Fix: .venv\\Scripts\\pip install groq   (or re-run setup.ps1)"
            )
    return problems


def _doctor() -> int:
    """Offline health check: prints what is configured and what is missing.

    Answers the two questions that actually block a first run — is a model
    provider reachable, and are the dependencies installed — without sending
    a single request that costs tokens.
    """
    import shutil
    import sys

    console = Console()
    console.print(f"[bold]⚡ F.R.I.D.A.Y[/bold] doctor — v{config.FRIDAY_VERSION}\n")
    problems: list[str] = []

    console.print(f"[cyan]python[/cyan]      {sys.version.split()[0]} ({sys.executable})")

    console.print(f"[cyan]project[/cyan]     {config.BASE_DIR}")
    console.print(f"[cyan].env[/cyan]        {'found' if (config.BASE_DIR / '.env').exists() else 'MISSING — copy .env.example'}")
    if not (config.BASE_DIR / ".env").exists():
        problems.append("no .env — run: cp .env.example .env")

    # --- provider chain -------------------------------------------------
    status = LLMEngine().get_model_status()
    chain = status.get("chain") or []
    console.print(f"[cyan]model[/cyan]       {status.get('active_model')}")
    console.print(f"[cyan]fallbacks[/cyan]   {max(0, len(chain) - 1)} {chain[1:] if len(chain) > 1 else ''}")
    if not chain:
        problems.append(
            "no usable model provider — set an API key in .env, or use local Ollama "
            "(FRIDAY_MODEL=ollama/llama3.2, OLLAMA_ENABLED=True)"
        )

    # --- optional SDKs ---------------------------------------------------
    missing = status.get("sdk_skipped") or []
    if missing:
        problems.append(f"SDK missing for: {', '.join(missing)} — pip install -r requirements.txt")

    # --- local Ollama, only when it is part of the chain ------------------
    if any(p == "ollama" for _, p in LLMEngine()._chain):
        base = config.OLLAMA_BASE_URL.strip().rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        # A real HTTP request, not a bare TCP connect: a socket can open while
        # TLS or the server itself is broken. Any HTTP answer means it is up.
        reachable, detail = False, ""
        try:
            import requests

            resp = requests.get(f"{base}/models", timeout=5)
            reachable, detail = resp.status_code < 500, f"HTTP {resp.status_code}"
        except Exception as e:  # noqa: BLE001 — doctor reports, never raises
            detail = type(e).__name__
        console.print(
            f"[cyan]ollama[/cyan]      {base} "
            f"{'reachable' if reachable else 'NOT reachable'} ({detail})"
        )
        console.print(f"[cyan]ollama bin[/cyan]  {shutil.which('ollama') or 'not installed'}")
        if not reachable:
            problems.append(
                f"Ollama is not answering at {base} — start it with `ollama serve` "
                "in another terminal (a Codespace restart stops it), or fix OLLAMA_BASE_URL"
            )

    # --- tools -----------------------------------------------------------
    discovery = ToolRegistry().auto_discover()
    console.print(f"[cyan]tools[/cyan]       {discovery['loaded']} loaded, {len(discovery['errors'])} errors")
    if discovery["errors"]:
        problems.append(f"tool import errors: {discovery['errors'][:3]}")

    console.print()
    if problems:
        console.print(f"[bold red]{len(problems)} problem(s):[/bold red]")
        for p in problems:
            console.print(f"  [red]•[/red] {p}")
        return 1
    console.print("[bold green]all good — run `python friday.py`[/bold green]")
    return 0


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="FRIDAY AI")
    parser.add_argument('--serve', action='store_true', help='run the HTTP daemon')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--token', default=None)
    parser.add_argument('--maintain', action='store_true',
                        help='run the daily system maintenance pass and exit '
                             '(used by the "FRIDAY Maintenance" scheduled task)')
    parser.add_argument('--deep', action='store_true',
                        help='with --maintain: deeper cleanup (component store, all temp files)')
    parser.add_argument('--doctor', action='store_true',
                        help='check the install, provider chain and local Ollama, then exit')
    parser.add_argument('--version', action='store_true', help='print the version and exit')
    args = parser.parse_args()
    if args.version:
        print(f"FRIDAY AI v{config.FRIDAY_VERSION}")
        return
    if args.doctor:
        raise SystemExit(_doctor())
    if args.maintain:
        from tools import maintenance_tools
        print(maintenance_tools.check_system_performance())
        print()
        print(maintenance_tools.run_maintenance(deep=args.deep))
        return
    if args.serve:
        from core.daemon import FridayDaemon
        FridayDaemon(args.host, args.port, args.token).serve()
        return
    console = Console()

    # 1 — initialize the stack
    memory = FridayMemory()
    engine = LLMEngine()
    registry = ToolRegistry()
    from tools import memory_tools

    memory_tools.bind_memory(memory)
    discovery = registry.auto_discover()
    from core.skills import SkillManager
    registry._skill_manager = SkillManager(registry)
    from tools import skill_tools
    skill_tools.bind_manager(registry._skill_manager)
    agent = AgentLoop(engine, registry, memory, console=console)

    # 2 — startup report
    status = engine.get_model_status()
    _banner(console, len(registry.tools), status)
    summary = memory.get_session_summary()
    console.print(
        f"[cyan]FRIDAY:[/cyan] v{config.FRIDAY_VERSION} online. "
        f"[bold]{len(registry.tools)} tools loaded[/bold]. "
        f"Memory: {summary['facts']} facts, {summary['tasks']} tasks on record."
    )
    if discovery["errors"]:
        console.print(
            f"[yellow]Warning: {len(discovery['errors'])} tool module(s) failed to load — "
            f"see logs/friday.log[/yellow]"
        )
    if not status["chain"]:
        console.print(
            "[red]No usable model configured. Add a provider API key, or set "
            "FRIDAY_MODEL=ollama/llama3.2 with OLLAMA_ENABLED=True.[/red]"
        )
    for problem in _sdk_problems():
        console.print(f"[yellow]⚠ {problem}[/yellow]")

    # 3 — main loop
    session_id = str(uuid.uuid4())
    console.print("[dim]Commands: help · tools · memory · status · clear · model <name> · exit[/dim]\n")

    while True:
        try:
            console.print("[bold white]Boss →[/bold white] ", end="")
            user_input = input().strip()
        except (EOFError, KeyboardInterrupt):
            user_input = "exit"
        if not user_input:
            continue
        low = user_input.lower()

        if low in ("exit", "quit", "bye"):
            console.print("[cyan]FRIDAY:[/cyan] Going offline, Boss. I'll be in the background.")
            break
        if low == "help":
            console.print(_HELP)
            continue
        if low == "tools":
            console.print(registry.list_tools())
            continue
        if low == "memory":
            s = memory.get_session_summary()
            console.print(
                f"Messages: {s['messages']} | Facts: {s['facts']} | Tasks: {s['tasks']} | "
                f"Tool calls: {s['tool_calls']} ({s['tool_success']} ok)\nDB: {s['db']}"
            )
            continue
        if low == "status":
            st = engine.get_model_status()
            console.print(
                f"Active model: [cyan]{st['active_model']}[/cyan] ({st['provider']})\n"
                f"Chain: {' → '.join(st['chain']) or '(none)'}\n"
                f"Calls: {st['calls']}\n"
                f"Last error: {st['last_error'] or 'none'}"
            )
            if st.get("sdk_skipped"):
                console.print(
                    f"[yellow]SDK missing (models offline): {', '.join(st['sdk_skipped'])} "
                    f"— fix: pip install -r requirements.txt[/yellow]"
                )
            continue
        if low == "clear":
            n = memory.clear_session(session_id)
            session_id = str(uuid.uuid4())
            console.print(
                f"[cyan]FRIDAY:[/cyan] Session memory wiped ({n} messages). Fresh start, Boss."
            )
            continue
        if low.startswith("model "):
            name = user_input.split(maxsplit=1)[1].strip()
            engine.set_primary_model(name)
            st = engine.get_model_status()
            console.print(
                f"[cyan]FRIDAY:[/cyan] Primary model set to [bold]{name}[/bold]. "
                f"Chain: {' → '.join(st['chain']) or '(none)'}"
            )
            continue

        config.logger.info("user: %s", user_input)
        try:
            agent.run(user_input, session_id)
        except Exception as e:  # noqa: BLE001 — the REPL must survive anything
            config.logger.exception("agent loop crashed")
            console.print(
                f"[red]✗ FRIDAY hit an unexpected error:[/red] {e}\n"
                "[dim]Your request was not lost — ask again and I'll reroute.[/dim]"
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFRIDAY: Going offline, Boss.")
        sys.exit(0)
