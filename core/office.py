"""Microsoft Office bridge — the Windows-only half of FRIDAY's Office support.

FRIDAY's Office tools are file-based first (python-docx / openpyxl /
python-pptx), so creating and reading documents works on any OS with no Office
installed. This module adds the things only the real applications can do:

    * export_pdf()  — true Office-quality PDF export
    * open_file()   — open a document in its actual app
    * com_app()     — a live COM handle for anything else

Every function degrades gracefully. On Linux/macOS, or on a Windows box with
no Office, PDF export falls back to LibreOffice's headless converter, and if
that is missing too the caller gets an OfficeUnavailable with an actionable
message rather than a traceback. Nothing here is imported at module load on
non-Windows systems.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import config

IS_WINDOWS = platform.system() == "Windows"

# COM ProgIDs for the apps FRIDAY drives.
PROG_IDS = {
    "word": "Word.Application",
    "excel": "Excel.Application",
    "powerpoint": "PowerPoint.Application",
}

# Office's numeric "save as PDF" format code, per app.
_PDF_FORMATS = {"word": 17, "excel": 0, "powerpoint": 32}


class OfficeUnavailable(RuntimeError):
    """Live Office automation is not possible here. Message says why and what to do."""


def availability() -> dict:
    """Describe what Office integration can do on this machine."""
    return {
        "platform": platform.system(),
        "com_automation": IS_WINDOWS and _has_pywin32(),
        "libreoffice": _soffice() is not None,
        "note": (
            "Full Office automation available."
            if IS_WINDOWS and _has_pywin32()
            else "File-based Office tools work normally; live app automation needs Windows + pywin32."
        ),
    }


def _has_pywin32() -> bool:
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def _soffice() -> str | None:
    """Path to a LibreOffice binary, if one is installed."""
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    if IS_WINDOWS:
        for candidate in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if Path(candidate).exists():
                return candidate
    return None


def require_com(app: str) -> None:
    """Raise a clear OfficeUnavailable unless live COM automation can run."""
    if app not in PROG_IDS:
        raise ValueError(f"unknown Office app: {app!r} (expected one of {sorted(PROG_IDS)})")
    if not IS_WINDOWS:
        raise OfficeUnavailable(
            f"Live {app.title()} automation needs Windows; this is {platform.system()}. "
            "The file-based tools (create/read/edit) work here — use those instead."
        )
    if not _has_pywin32():
        raise OfficeUnavailable(
            "pywin32 is not installed, so FRIDAY cannot talk to Office. Run: pip install pywin32"
        )


@contextmanager
def com_app(app: str, visible: bool = False):
    """Yield a live COM handle to Word/Excel/PowerPoint, quitting it afterwards.

    The app is only quit if *we* started it, so an Office window the Boss
    already had open is never closed underneath them.
    """
    require_com(app)
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    pythoncom.CoInitialize()
    handle = None
    started_by_us = False
    try:
        try:
            handle = win32com.client.GetActiveObject(PROG_IDS[app])
        except Exception:  # noqa: BLE001 — not running yet, so start it
            handle = win32com.client.Dispatch(PROG_IDS[app])
            started_by_us = True
        # PowerPoint refuses to be invisible; the others honour it.
        if app != "powerpoint":
            try:
                handle.Visible = visible
            except Exception as e:  # noqa: BLE001
                config.logger.debug("could not set %s visibility: %s", app, e)
        yield handle
    except OfficeUnavailable:
        raise
    except Exception as e:  # noqa: BLE001
        raise OfficeUnavailable(f"{app.title()} COM automation failed: {type(e).__name__}: {e}") from e
    finally:
        if handle is not None and started_by_us:
            try:
                handle.Quit()
            except Exception as e:  # noqa: BLE001
                config.logger.debug("could not quit %s: %s", app, e)
        try:
            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass


def _export_pdf_com(app: str, src: Path, dest: Path) -> None:
    """Export via the real Office app (best fidelity)."""
    with com_app(app) as handle:
        if app == "word":
            doc = handle.Documents.Open(str(src), ReadOnly=True)
            try:
                doc.SaveAs(str(dest), FileFormat=_PDF_FORMATS["word"])
            finally:
                doc.Close(False)
        elif app == "excel":
            wb = handle.Workbooks.Open(str(src), ReadOnly=True)
            try:
                wb.ExportAsFixedFormat(_PDF_FORMATS["excel"], str(dest))
            finally:
                wb.Close(False)
        else:
            pres = handle.Presentations.Open(str(src), WithWindow=False)
            try:
                pres.SaveAs(str(dest), _PDF_FORMATS["powerpoint"])
            finally:
                pres.Close()


def _export_pdf_soffice(src: Path, dest: Path) -> None:
    """Export via headless LibreOffice (the cross-platform fallback)."""
    binary = _soffice()
    if binary is None:
        raise OfficeUnavailable(
            "Cannot export to PDF: no Microsoft Office (COM) and no LibreOffice on this system. "
            "Install LibreOffice, or run this on the Windows box where Office lives."
        )
    try:
        proc = subprocess.run(
            [binary, "--headless", "--convert-to", "pdf", "--outdir", str(dest.parent), str(src)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as e:
        raise OfficeUnavailable("LibreOffice PDF conversion timed out after 180s") from e
    produced = dest.parent / (src.stem + ".pdf")
    if not produced.exists():
        raise OfficeUnavailable(
            f"LibreOffice could not convert {src.name}: {(proc.stderr or proc.stdout or '').strip()[:300]}"
        )
    if produced != dest:
        shutil.move(str(produced), str(dest))


def export_pdf(app: str, source: str | Path, output: str | Path | None = None) -> str:
    """Convert an Office document to PDF. Returns the PDF path.

    Tries real Office via COM first, then headless LibreOffice.
    """
    src = Path(source).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"file not found: {src}")
    dest = Path(output).expanduser() if output else src.with_suffix(".pdf")
    if not dest.is_absolute():
        dest = Path.cwd() / dest
    dest.parent.mkdir(parents=True, exist_ok=True)

    if IS_WINDOWS and _has_pywin32():
        try:
            _export_pdf_com(app, src, dest)
            return str(dest)
        except Exception as e:  # noqa: BLE001 — fall through to LibreOffice
            config.logger.warning("COM PDF export failed (%s) — trying LibreOffice", e)
    _export_pdf_soffice(src, dest)
    return str(dest)


def open_file(path: str | Path) -> str:
    """Open a document in whatever app owns it. Returns a status line."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    try:
        if IS_WINDOWS:
            os.startfile(str(p))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            opener = shutil.which("xdg-open")
            if opener is None:
                raise OfficeUnavailable(
                    f"No desktop opener available on this system — the file is ready at {p}"
                )
            subprocess.Popen([opener, str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OfficeUnavailable:
        raise
    except OSError as e:
        raise OfficeUnavailable(f"could not open {p.name}: {e}") from e
    return f"Opened {p} in its default application."
