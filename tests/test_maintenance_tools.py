"""Tests for the maintenance tools — performance checks and daily upkeep.

All runs are redirected to tmp_path: history file, maintenance report dir
and the temp folders that get cleaned, so a test never touches the real
system temp or the developer's maintenance history.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tools import maintenance_tools as mt


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Redirect history, report dir and temp dirs into tmp_path."""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(mt, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(mt, "MAINT_LOG_DIR", tmp_path / "reports")
    monkeypatch.setattr(mt, "_temp_dirs", lambda: [temp_dir])
    return temp_dir


def _make_old_file(directory: Path, name: str, age_hours: float, size: int = 1024) -> Path:
    p = directory / name
    p.write_bytes(b"x" * size)
    old = time.time() - age_hours * 3600
    os.utime(p, (old, old))
    return p


def test_performance_report_has_score_and_sections(sandbox):
    report = mt.check_system_performance()
    assert "SYSTEM HEALTH SCORE:" in report
    assert "CPU:" in report
    assert "RAM:" in report
    assert "Top memory users:" in report
    score = int(report.split("SYSTEM HEALTH SCORE:")[1].split("/")[0].strip())
    assert 0 <= score <= 100


def test_maintenance_removes_only_old_temp_files(sandbox):
    old = _make_old_file(sandbox, "old.tmp", age_hours=48)
    fresh = sandbox / "fresh.tmp"
    fresh.write_bytes(b"keep me")

    report = mt.run_maintenance()

    assert "MAINTENANCE COMPLETE" in report
    assert not old.exists(), "48h-old temp file should be removed"
    assert fresh.exists(), "fresh temp file must be kept on a daily run"


def test_deep_maintenance_removes_recent_files_too(sandbox):
    recent = _make_old_file(sandbox, "recent.tmp", age_hours=2)
    mt.run_maintenance(deep=True)
    assert not recent.exists(), "deep run clears files older than 1h"


def test_maintenance_records_history(sandbox):
    _make_old_file(sandbox, "junk.tmp", age_hours=30, size=2048)
    mt.run_maintenance()
    entries = json.loads(mt.HISTORY_PATH.read_text(encoding="utf-8"))
    assert len(entries) == 1
    e = entries[0]
    assert e["files_removed"] == 1
    assert e["deep"] is False
    assert "timestamp" in e and "actions" in e


def test_maintenance_writes_dated_report_file(sandbox):
    mt.run_maintenance()
    reports = list(mt.MAINT_LOG_DIR.glob("*.txt"))
    assert len(reports) == 1
    assert "MAINTENANCE COMPLETE" in reports[0].read_text(encoding="utf-8")


def test_history_summary_after_runs(sandbox):
    assert "No maintenance runs recorded" in mt.get_maintenance_history()
    mt.run_maintenance()
    mt.run_maintenance(deep=True)
    out = mt.get_maintenance_history(limit=5)
    assert "2 maintenance run(s)" in out
    assert "deep" in out and "daily" in out


def test_history_survives_corrupt_file(sandbox):
    mt.HISTORY_PATH.write_text("{not valid json", encoding="utf-8")
    mt.run_maintenance()  # must not raise
    entries = json.loads(mt.HISTORY_PATH.read_text(encoding="utf-8"))
    assert len(entries) == 1


def test_startup_programs_returns_text(sandbox):
    out = mt.list_startup_programs()
    assert isinstance(out, str) and out.strip()


def test_tools_register(sandbox):
    from core.tool_registry import ToolRegistry

    registry = ToolRegistry()
    mt.register_tools(registry)
    for name in (
        "check_system_performance",
        "run_maintenance",
        "get_maintenance_history",
        "list_startup_programs",
    ):
        assert name in registry.tools
