"""Streaming response handler — the human-visible side of LLM events.

The LLM engine yields raw events (text chunks, function calls). This module
renders them: a Rich Live "tail" display while tokens arrive (transient — it
clears itself), full Markdown rendering for the final answer, and the styled
tool/thinking lines (⚡ Using / ✓ Done / ✗ Failed / ◈ Analyzing).
"""
from __future__ import annotations

import json

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

import config


class StreamingDisplay:
    """Rich Live region that shows the tail of the streamed text, then clears."""

    def __init__(self, console: Console, enabled: bool = True) -> None:
        self.console = console
        self.enabled = enabled
        self._live: Live | None = None
        self._buf = ""

    def __enter__(self) -> "StreamingDisplay":
        if self.enabled and config.STREAMING:
            self._live = Live(Text(""), console=self.console, refresh_per_second=15, transient=True)
            self._live.start()
        return self

    def add_text(self, chunk: str) -> None:
        self._buf += chunk
        if self._live is not None:
            self._live.update(Text("◈ " + self._buf[-500:], style="cyan"))

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._live is not None:
            self._live.stop()
        return False


def render_final(console: Console, text: str) -> None:
    """Final answer: rule + full Rich Markdown rendering."""
    console.rule("[cyan]FRIDAY[/cyan]", style="cyan")
    console.print(Markdown(text))


def format_thinking(iteration: int) -> str:
    return f"[dim]◈ Analyzing… (pass {iteration})[/dim]"


def format_tool_start(name: str, args: dict) -> str:
    args_brief = json.dumps(args or {}, ensure_ascii=False)
    if len(args_brief) > 90:
        args_brief = args_brief[:90] + "…"
    return f"[yellow]⚡ Using:[/yellow] [bold]{name}[/bold] [dim]→ {args_brief}[/dim]"


def format_tool_done(result: str) -> str:
    brief = result.replace("\n", " ")[:90]
    return f"[green]✓ Done[/green] [dim]({len(result)} chars) {brief}[/dim]"


def format_tool_fail(error: str) -> str:
    return f"[red]✗ Failed:[/red] {str(error)[:120]} [dim]— trying another approach…[/dim]"


def format_friday_note(text: str) -> str:
    """Intermediate 'thinking aloud' text from a round that also called tools."""
    return f"[cyan]FRIDAY:[/cyan] [dim]{text[:400]}[/dim]"
