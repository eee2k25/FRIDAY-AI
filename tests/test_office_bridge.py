"""Tests for the Office/COM bridge and its graceful degradation."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import office
from core.office import OfficeUnavailable


def test_availability_reports_this_platform():
    info = office.availability()
    assert set(info) == {"platform", "com_automation", "libreoffice", "note"}
    assert isinstance(info["com_automation"], bool)


def test_require_com_rejects_unknown_app():
    with pytest.raises(ValueError, match="unknown Office app"):
        office.require_com("notepad")


def test_require_com_off_windows_is_actionable(monkeypatch):
    monkeypatch.setattr(office, "IS_WINDOWS", False)
    with pytest.raises(OfficeUnavailable, match="needs Windows"):
        office.require_com("word")


def test_require_com_without_pywin32_names_the_fix(monkeypatch):
    monkeypatch.setattr(office, "IS_WINDOWS", True)
    monkeypatch.setattr(office, "_has_pywin32", lambda: False)
    with pytest.raises(OfficeUnavailable, match="pip install pywin32"):
        office.require_com("word")


def test_export_pdf_missing_source():
    with pytest.raises(FileNotFoundError):
        office.export_pdf("word", "/nope/missing.docx")


def test_export_pdf_without_office_or_libreoffice_explains(monkeypatch, tmp_path):
    src = tmp_path / "a.docx"
    src.write_bytes(b"stub")
    monkeypatch.setattr(office, "IS_WINDOWS", False)
    monkeypatch.setattr(office, "_soffice", lambda: None)
    with pytest.raises(OfficeUnavailable, match="no Microsoft Office"):
        office.export_pdf("word", src)


def test_export_pdf_uses_libreoffice_when_present(monkeypatch, tmp_path):
    src = tmp_path / "a.docx"
    src.write_bytes(b"stub")
    monkeypatch.setattr(office, "IS_WINDOWS", False)
    monkeypatch.setattr(office, "_soffice", lambda: "/usr/bin/soffice")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")

        class R:
            stderr = ""
            stdout = ""

        return R()

    monkeypatch.setattr(office.subprocess, "run", fake_run)
    out = office.export_pdf("word", src)
    assert Path(out).exists()
    assert "--headless" in captured["cmd"]


def test_export_pdf_honours_a_custom_output_path(monkeypatch, tmp_path):
    src = tmp_path / "a.docx"
    src.write_bytes(b"stub")
    dest = tmp_path / "out" / "custom.pdf"
    monkeypatch.setattr(office, "IS_WINDOWS", False)
    monkeypatch.setattr(office, "_soffice", lambda: "/usr/bin/soffice")

    def fake_run(cmd, **kwargs):
        (dest.parent / "a.pdf").write_bytes(b"%PDF fake")

        class R:
            stderr = ""
            stdout = ""

        return R()

    monkeypatch.setattr(office.subprocess, "run", fake_run)
    assert office.export_pdf("word", src, dest) == str(dest)
    assert dest.exists()


def test_export_pdf_reports_libreoffice_failure(monkeypatch, tmp_path):
    src = tmp_path / "a.docx"
    src.write_bytes(b"stub")
    monkeypatch.setattr(office, "IS_WINDOWS", False)
    monkeypatch.setattr(office, "_soffice", lambda: "/usr/bin/soffice")

    def fake_run(cmd, **kwargs):
        class R:
            stderr = "conversion exploded"
            stdout = ""

        return R()

    monkeypatch.setattr(office.subprocess, "run", fake_run)
    with pytest.raises(OfficeUnavailable, match="conversion exploded"):
        office.export_pdf("word", src)


def test_open_file_missing():
    with pytest.raises(FileNotFoundError):
        office.open_file("/nope/missing.docx")


def test_open_file_without_a_desktop_opener(monkeypatch, tmp_path):
    f = tmp_path / "a.docx"
    f.write_bytes(b"stub")
    monkeypatch.setattr(office, "IS_WINDOWS", False)
    monkeypatch.setattr(office.sys, "platform", "linux")
    monkeypatch.setattr(office.shutil, "which", lambda n: None)
    with pytest.raises(OfficeUnavailable, match="ready at"):
        office.open_file(f)


def test_open_file_uses_xdg_open(monkeypatch, tmp_path):
    f = tmp_path / "a.docx"
    f.write_bytes(b"stub")
    captured = {}
    monkeypatch.setattr(office, "IS_WINDOWS", False)
    monkeypatch.setattr(office.sys, "platform", "linux")
    monkeypatch.setattr(office.shutil, "which", lambda n: "/usr/bin/xdg-open")
    monkeypatch.setattr(office.subprocess, "Popen", lambda cmd, **kw: captured.setdefault("cmd", cmd))
    assert "Opened" in office.open_file(f)
    assert captured["cmd"][0] == "/usr/bin/xdg-open"


def test_office_status_tool_never_raises():
    from tools.word_tools import office_status

    out = office_status()
    assert "Platform:" in out and "LibreOffice:" in out


def test_word_to_pdf_missing_document():
    from tools.word_tools import word_to_pdf

    with pytest.raises(FileNotFoundError):
        word_to_pdf("/nope/missing.docx")
