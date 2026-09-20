"""System tools — shell commands, Python execution, launching apps, system
info, process list, clipboard, current time.

Safety: commands run in a subprocess with a hard timeout. FRIDAY announces
every command in the console before it runs (see agent_loop).
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import config


def _format_result(proc: subprocess.CompletedProcess, extra: str = "") -> str:
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parts = [f"EXIT CODE: {proc.returncode}"]
    if out:
        parts.append(f"STDOUT:\n{out[:8000]}")
    if err:
        parts.append(f"STDERR:\n{err[:4000]}")
    if not out and not err:
        parts.append("(completed silently, no output)")
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def run_command(command: str, timeout: int = 30) -> str:
    """Run a shell command (cmd.exe on Windows) and return stdout/stderr/exit code."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=int(timeout) or 30,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"command timed out after {timeout}s: {command[:80]}")
    except OSError as e:
        raise RuntimeError(f"could not run command: {e}")
    return _format_result(proc)


def run_python_script(script_path: str, args: str = "") -> str:
    """Run a Python file with the active interpreter and capture output."""
    p = Path(script_path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        raise FileNotFoundError(f"script not found: {p}")
    cmd = [sys.executable, str(p)] + (shlex.split(args) if args else [])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace"
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"script timed out after 60s: {p.name}")
    return _format_result(proc)


def run_python_code(code: str) -> str:
    """Execute a Python code string in a fresh subprocess (not exec) with a 30s timeout."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="friday_"))
    tmp = tmp_dir / "snippet.py"
    tmp.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(tmp)],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError("code execution timed out after 30s")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return _format_result(proc, extra=f"[source saved at {tmp} for inspection]")


def run_powershell(command: str, timeout: int = 60) -> str:
    """Run a PowerShell command (pwsh if present, else powershell.exe) and
    return stdout, stderr and exit code. Use for Windows system work:
    services, processes, env vars, files, registry, networks.

    Notes: separate statements with ';' (PowerShell has no &&), wrap paths in
    double quotes, and remember $ variables are expanded by PowerShell.
    """
    ps = shutil.which("pwsh") or ("powershell.exe" if os.name == "nt" else None)
    if ps is None:
        raise RuntimeError("PowerShell not found on this system")
    try:
        proc = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=int(timeout) or 60,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"PowerShell command timed out after {timeout}s: {command[:80]}")
    except OSError as e:
        raise RuntimeError(f"could not run PowerShell: {e}")
    if proc.returncode != 0:
        return _format_result(proc) + "\n\n[non-zero exit — read the STDERR above, fix the cause, and retry]"
    return _format_result(proc)


def check_own_logs(lines: int = 40) -> str:
    """Tail FRIDAY's own log file — use this to self-diagnose recent failures
    (model errors, tool errors) before reporting them to the Boss."""
    p = config.LOG_PATH
    if not p.exists():
        return "(no log file yet)"
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-max(1, int(lines)):]
    except OSError as e:
        raise RuntimeError(f"could not read log: {e}")
    return "".join(tail) or "(empty log)"


_APP_MAP = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "notepad": "notepad",
    "calculator": "calc",
    "file explorer": "explorer",
    "explorer": "explorer",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "terminal": "cmd",
    "cmd": "cmd",
    "powershell": "powershell",
}


def open_application(app_name: str) -> str:
    """Open a common application by name (chrome, word, excel, vscode, ...)."""
    target = _APP_MAP.get(app_name.lower().strip(), app_name)
    if os.name == "nt":
        try:
            subprocess.Popen([target], shell=True)
        except OSError as e:
            raise RuntimeError(f"could not open {app_name}: {e}")
        return f"Opened {app_name}."
    exe = shutil.which(target)
    if exe is None:
        raise RuntimeError(f"application not found on this system: {app_name}")
    subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opened {app_name}."


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError as e:
        raise RuntimeError("psutil not installed. Run: pip install psutil") from e


def get_system_info() -> str:
    """CPU%, RAM, disk space, process count, boot time."""
    psutil = _psutil()
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk_root = "C:\\" if os.name == "nt" else "/"
    disk = psutil.disk_usage(disk_root)
    procs = len(psutil.pids())
    return (
        f"CPU:       {cpu}% ({psutil.cpu_count(logical=True)} logical cores)\n"
        f"RAM:       {mem.percent}% used — {mem.used / 2**30:.1f} / {mem.total / 2**30:.1f} GB\n"
        f"Disk {disk_root}:   {disk.percent}% used — {disk.free / 2**30:.1f} GB free\n"
        f"Processes: {procs}\n"
        f"Booted:    {datetime.fromtimestamp(psutil.boot_time()):%Y-%m-%d %H:%M}"
    )


def list_running_processes(filter_name: str = "") -> str:
    """List processes (PID, name, memory), optionally filtered by name."""
    psutil = _psutil()
    out, n = [], 0
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        name = proc.info.get("name") or ""
        if filter_name and filter_name.lower() not in name.lower():
            continue
        mem = proc.info.get("memory_info")
        mb = f"{mem.rss / 2**20:.0f} MB" if mem else "?"
        out.append(f"PID {proc.info['pid']:<8} {name[:40]:<40} {mb}")
        n += 1
        if n >= 100:
            break
    if not out:
        return f"No processes matching {filter_name!r}."
    return f"{n} process(es):\n" + "\n".join(out)


def _pyperclip():
    try:
        import pyperclip
        return pyperclip
    except ImportError as e:
        raise RuntimeError("pyperclip not installed. Run: pip install pyperclip") from e


def get_clipboard() -> str:
    """Return the current clipboard text."""
    text = _pyperclip().paste() or ""
    return text.strip() or "(clipboard is empty)"


def set_clipboard(text: str) -> str:
    """Set the clipboard to the given text."""
    _pyperclip().copy(text)
    return f"Clipboard set ({len(text)} chars)."


def get_current_time() -> str:
    """Current local date, time and timezone offset."""
    now = datetime.now().astimezone()
    offset = now.utcoffset()
    offset_s = str(offset).replace("days, ", "") if offset is not None else "unknown"
    return f"{now:%A %d %B %Y %H:%M:%S} (UTC offset {offset_s})"


_DECLARATIONS: list[dict] = [
    {
        "name": "run_command",
        "description": "Run a shell command (cmd on Windows) and return stdout, stderr and exit code. Use for system tasks, directory ops, git-less checks.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The exact shell command to run"},
                "timeout": {"type": "integer", "description": "max seconds, default 30"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "run_python_script",
        "description": "Run an existing .py file and capture its output.",
        "parameters": {
            "type": "object",
            "properties": {
                "script_path": {"type": "string"},
                "args": {"type": "string", "description": "optional space-separated arguments"},
            },
            "required": ["script_path"],
        },
    },
    {
        "name": "run_python_code",
        "description": "Execute a Python code string in a fresh subprocess (30s timeout) and return its output.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python source code to execute"}},
            "required": ["code"],
        },
    },
    {
        "name": "run_powershell",
        "description": "Run a PowerShell command and return stdout, stderr and exit code. Use for Windows system work (services, processes, env vars, files, networks). On error: read the STDERR, fix the cause (quoting/paths/admin), and retry.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell command(s); separate statements with ';'"},
                "timeout": {"type": "integer", "description": "max seconds, default 60"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "check_own_logs",
        "description": "Read the last N lines of FRIDAY's own log file. Use to self-diagnose recent model/tool failures before reporting them.",
        "parameters": {
            "type": "object",
            "properties": {"lines": {"type": "integer", "description": "how many tail lines, default 40"}},
        },
    },
    {
        "name": "open_application",
        "description": "Open a common application by name: chrome, edge, word, excel, powerpoint, notepad, calculator, file explorer, vscode, terminal.",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
    {
        "name": "get_system_info",
        "description": "CPU usage, RAM used/total, disk space, process count, boot time.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_running_processes",
        "description": "List running processes (PID, name, memory), optionally filtered by a name substring.",
        "parameters": {
            "type": "object",
            "properties": {"filter_name": {"type": "string", "description": "optional filter, e.g. 'chrome'"}},
        },
    },
    {
        "name": "get_clipboard",
        "description": "Read the current clipboard text.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "set_clipboard",
        "description": "Set the clipboard to the given text.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "get_current_time",
        "description": "Current local date, time and UTC offset.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
