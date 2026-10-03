"""Maintenance tools — system performance health checks and day-by-day PC
upkeep.

This module powers two things:

1. Chat tools — the Boss can ask FRIDAY "check system performance" or
   "run maintenance" at any time.
2. The daily "FRIDAY Maintenance" scheduled task created by setup.ps1, which
   calls ``friday.py --maintain`` every day with admin rights so the machine
   stays fast without anyone thinking about it.

Everything is deliberately conservative: only known-safe junk is removed
(temp files older than a day, stale FRIDAY logs, DNS cache). Nothing a user
could miss is ever touched. Every run is recorded to
memory/maintenance_history.json so FRIDAY can report trends over time.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import config

HISTORY_PATH = config.BASE_DIR / "memory" / "maintenance_history.json"
MAINT_LOG_DIR = config.BASE_DIR / "logs" / "maintenance"

_IS_WINDOWS = os.name == "nt"


def _psutil():
    try:
        import psutil
        return psutil
    except ImportError as e:  # pragma: no cover - psutil is in requirements
        raise RuntimeError("psutil not installed. Run: pip install psutil") from e


# ===================================================================== #
#  Performance check                                                     #
# ===================================================================== #

def _dir_size(path: Path, limit_files: int = 50000) -> int:
    total, seen = 0, 0
    try:
        for p in path.rglob("*"):
            seen += 1
            if seen > limit_files:
                break
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _temp_dirs() -> list[Path]:
    dirs = [Path(tempfile.gettempdir())]
    if _IS_WINDOWS:
        win_temp = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"
        if win_temp.exists() and win_temp not in dirs:
            dirs.append(win_temp)
    return dirs


def _top_processes(psutil, key: str, n: int = 5) -> list[str]:
    procs = []
    for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
        try:
            name = p.info.get("name") or "?"
            if key == "cpu":
                val = p.info.get("cpu_percent") or 0.0
                procs.append((val, f"{name[:32]:<32} {val:5.1f}% CPU"))
            else:
                mem = p.info.get("memory_info")
                rss = mem.rss if mem else 0
                procs.append((rss, f"{name[:32]:<32} {rss / 2**20:7.0f} MB"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda t: t[0], reverse=True)
    return [line for _, line in procs[:n]]


def check_system_performance() -> str:
    """Full PC health report: CPU, RAM, disks, temp-junk size, top resource
    hogs, uptime — plus a 0-100 health score and concrete recommendations."""
    psutil = _psutil()
    psutil.cpu_percent(interval=None)       # prime the counters
    time.sleep(0.6)
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    boot = datetime.fromtimestamp(psutil.boot_time())
    uptime_days = (datetime.now() - boot).total_seconds() / 86400

    # disks
    disk_lines, worst_disk = [], 0.0
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            du = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        worst_disk = max(worst_disk, du.percent)
        disk_lines.append(
            f"  {part.mountpoint:<8} {du.percent:5.1f}% used — {du.free / 2**30:7.1f} GB free"
        )

    temp_bytes = sum(_dir_size(d) for d in _temp_dirs())

    # health score
    score, issues = 100, []
    if cpu > 85:
        score -= 20; issues.append(f"CPU is under heavy load ({cpu:.0f}%) — check the top processes below.")
    elif cpu > 60:
        score -= 10; issues.append(f"CPU load is elevated ({cpu:.0f}%).")
    if mem.percent > 90:
        score -= 20; issues.append(f"RAM nearly full ({mem.percent:.0f}%) — close unused apps or add memory.")
    elif mem.percent > 75:
        score -= 10; issues.append(f"RAM usage is high ({mem.percent:.0f}%).")
    if worst_disk > 90:
        score -= 20; issues.append(f"A disk is {worst_disk:.0f}% full — free space is critical for performance.")
    elif worst_disk > 80:
        score -= 10; issues.append(f"A disk is {worst_disk:.0f}% full — consider cleaning up.")
    if temp_bytes > 2 * 2**30:
        score -= 10; issues.append(f"{temp_bytes / 2**30:.1f} GB of temp junk — run_maintenance will clear it.")
    elif temp_bytes > 500 * 2**20:
        score -= 5; issues.append(f"{temp_bytes / 2**20:.0f} MB of temp files can be cleaned.")
    if uptime_days > 14:
        score -= 10; issues.append(f"Up {uptime_days:.0f} days without a restart — a reboot would help.")
    elif uptime_days > 7:
        score -= 5; issues.append(f"Up {uptime_days:.0f} days — consider a restart soon.")
    score = max(0, score)
    verdict = ("EXCELLENT" if score >= 90 else "GOOD" if score >= 75 else
               "NEEDS ATTENTION" if score >= 50 else "POOR")

    lines = [
        f"SYSTEM HEALTH SCORE: {score}/100 — {verdict}",
        "",
        f"CPU:     {cpu:.1f}% ({psutil.cpu_count(logical=True)} logical cores)",
        f"RAM:     {mem.percent:.1f}% used — {mem.used / 2**30:.1f} / {mem.total / 2**30:.1f} GB",
        "Disks:",
        *(disk_lines or ["  (no disks found)"]),
        f"Temp junk: {temp_bytes / 2**20:.0f} MB across {len(_temp_dirs())} temp folder(s)",
        f"Uptime:  {uptime_days:.1f} days (booted {boot:%Y-%m-%d %H:%M})",
        "",
        "Top memory users:",
        *(f"  {l}" for l in _top_processes(psutil, "mem")),
        "Top CPU users:",
        *(f"  {l}" for l in _top_processes(psutil, "cpu")),
    ]
    if issues:
        lines += ["", "Recommendations:"] + [f"  - {i}" for i in issues]
    else:
        lines += ["", "No issues found — the machine is in great shape, Boss."]
    return "\n".join(lines)


# ===================================================================== #
#  Maintenance                                                           #
# ===================================================================== #

def _clean_temp(older_than_hours: float) -> tuple[int, int]:
    """Delete temp files older than N hours. Returns (files_removed, bytes_freed)."""
    cutoff = time.time() - older_than_hours * 3600
    removed, freed = 0, 0
    for root in _temp_dirs():
        if not root.exists():
            continue
        for p in list(root.rglob("*"))[:100000]:
            try:
                if not p.is_file() or p.stat().st_mtime > cutoff:
                    continue
                size = p.stat().st_size
                p.unlink()
                removed += 1
                freed += size
            except OSError:
                continue            # in use / permission — skip silently
        # sweep now-empty subdirectories
        for d in sorted((d for d in root.rglob("*") if d.is_dir()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                continue
    return removed, freed


def _trim_friday_logs(max_mb: int = 10) -> str | None:
    log = config.LOG_PATH
    try:
        if log.exists() and log.stat().st_size > max_mb * 2**20:
            tail = log.read_text(encoding="utf-8", errors="replace")[-2**20:]
            log.write_text(tail, encoding="utf-8")
            return f"trimmed logs/friday.log to its last 1 MB (was > {max_mb} MB)"
    except OSError:
        pass
    return None


def _run_quiet(cmd: list[str], timeout: int = 900) -> bool:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _load_history() -> list[dict]:
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_history(entries: list[dict]) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(entries[-120:], indent=2), encoding="utf-8")
    except OSError:
        config.logger.warning("could not write maintenance history")


def run_maintenance(deep: bool = False) -> str:
    """Run FRIDAY's safe daily tune-up: clear old temp files, flush the DNS
    cache, trim oversized logs; ``deep=True`` adds Windows component-store
    cleanup. Only known-safe junk is touched. Results are logged to history."""
    psutil = _psutil()
    started = datetime.now()
    actions: list[str] = []

    # 1 — temp files (normal: older than 24h, deep: older than 1h)
    removed, freed = _clean_temp(older_than_hours=1 if deep else 24)
    actions.append(f"removed {removed} temp file(s), freed {freed / 2**20:.1f} MB")

    # 2 — DNS cache (Windows)
    if _IS_WINDOWS and _run_quiet(["ipconfig", "/flushdns"], timeout=30):
        actions.append("flushed the DNS resolver cache")

    # 3 — FRIDAY's own logs
    trimmed = _trim_friday_logs()
    if trimmed:
        actions.append(trimmed)

    # 4 — deep: Windows component store cleanup (reclaims WinSxS space)
    if deep and _IS_WINDOWS:
        if _run_quiet(["dism", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], timeout=1800):
            actions.append("cleaned the Windows component store (DISM)")
        else:
            actions.append("component store cleanup skipped (needs admin or DISM busy)")

    # 5 — snapshot for the history log
    mem = psutil.virtual_memory()
    disk_root = "C:\\" if _IS_WINDOWS else "/"
    try:
        disk = psutil.disk_usage(disk_root)
        disk_pct, disk_free_gb = disk.percent, disk.free / 2**30
    except OSError:
        disk_pct, disk_free_gb = 0.0, 0.0

    entry = {
        "timestamp": started.isoformat(timespec="seconds"),
        "deep": bool(deep),
        "files_removed": removed,
        "mb_freed": round(freed / 2**20, 1),
        "ram_percent": mem.percent,
        "disk_percent": disk_pct,
        "disk_free_gb": round(disk_free_gb, 1),
        "actions": actions,
    }
    history = _load_history()
    history.append(entry)
    _save_history(history)

    duration = (datetime.now() - started).total_seconds()
    report = [
        f"MAINTENANCE COMPLETE ({'deep' if deep else 'daily'}) — {duration:.0f}s",
        *(f"  - {a}" for a in actions),
        "",
        f"After cleanup: RAM {mem.percent:.0f}% | disk {disk_root} {disk_pct:.0f}% used "
        f"({disk_free_gb:.1f} GB free)",
        f"History: {len(history)} run(s) recorded in memory/maintenance_history.json",
    ]
    text = "\n".join(report)

    # also drop a dated report file so the scheduled task leaves a paper trail
    try:
        MAINT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        (MAINT_LOG_DIR / f"{started:%Y-%m-%d}.txt").write_text(
            text + "\n", encoding="utf-8"
        )
    except OSError:
        pass
    config.logger.info("maintenance run: %s", entry)
    return text


def get_maintenance_history(limit: int = 10) -> str:
    """Show the last N daily-maintenance runs: when, what was cleaned, and
    how RAM/disk looked — so FRIDAY can spot trends day by day."""
    history = _load_history()
    if not history:
        return "No maintenance runs recorded yet. Run run_maintenance first."
    rows = []
    for e in history[-max(1, int(limit)):]:
        rows.append(
            f"{e.get('timestamp', '?'):<20} "
            f"{'deep ' if e.get('deep') else 'daily'} | "
            f"{e.get('files_removed', 0):>5} files, {e.get('mb_freed', 0):>8} MB freed | "
            f"RAM {e.get('ram_percent', 0):>4}% | disk {e.get('disk_percent', 0):>4}% "
            f"({e.get('disk_free_gb', 0)} GB free)"
        )
    total_mb = sum(float(e.get("mb_freed", 0)) for e in history)
    return (
        f"Last {len(rows)} maintenance run(s) (of {len(history)} total, "
        f"{total_mb:.0f} MB reclaimed all-time):\n" + "\n".join(rows)
    )


def list_startup_programs() -> str:
    """List programs that launch at startup/login — the usual cause of a slow
    boot. On Windows this reads the registry Run keys and Startup folders."""
    if _IS_WINDOWS:
        ps = (
            "Get-CimInstance Win32_StartupCommand | "
            "Select-Object Name, Command, Location | "
            "Format-Table -AutoSize | Out-String -Width 300"
        )
        exe = shutil.which("powershell") or shutil.which("pwsh")
        if not exe:
            return "PowerShell not found — cannot enumerate startup programs."
        try:
            proc = subprocess.run(
                [exe, "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"could not list startup programs: {e}") from e
        out = (proc.stdout or "").strip()
        if not out:
            return "No startup programs found."
        return (
            out[:8000]
            + "\n\nTip: disable anything you don't need in Task Manager > Startup apps "
              "— each entry slows the boot."
        )
    # non-Windows: autostart desktop entries
    autostart = Path.home() / ".config" / "autostart"
    entries = sorted(p.name for p in autostart.glob("*.desktop")) if autostart.exists() else []
    if not entries:
        return "No autostart entries found."
    return "Autostart entries:\n" + "\n".join(f"  - {e}" for e in entries)


# ===================================================================== #
#  Registration                                                          #
# ===================================================================== #

_DECLARATIONS: list[dict] = [
    {
        "name": "check_system_performance",
        "description": (
            "Full PC health report with a 0-100 score: CPU, RAM, every disk, "
            "temp-junk size, uptime, top resource-hogging processes, and "
            "concrete recommendations. Use when the Boss asks how the PC is "
            "doing, why it is slow, or before/after maintenance."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "run_maintenance",
        "description": (
            "Run FRIDAY's safe system tune-up: clear old temp files, flush DNS "
            "cache, trim oversized logs. deep=true additionally runs Windows "
            "component-store cleanup (slower, admin). Only known-safe junk is "
            "removed. Also what the daily 'FRIDAY Maintenance' task runs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deep": {
                    "type": "boolean",
                    "description": "true = deep cleanup (slower, more thorough), default false",
                }
            },
        },
    },
    {
        "name": "get_maintenance_history",
        "description": (
            "Show the last N recorded maintenance runs (date, files removed, MB "
            "freed, RAM/disk state) to track the PC's condition day by day."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "how many recent runs, default 10"}
            },
        },
    },
    {
        "name": "list_startup_programs",
        "description": (
            "List programs that launch at startup/login — the usual cause of a "
            "slow boot. Suggest disabling the unnecessary ones."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
