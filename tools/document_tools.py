"""Backwards-compatibility shim.

Office support was split into focused modules as it grew:

    Word        → tools/word_tools.py        (v1.3.0)
    PowerPoint  → tools/powerpoint_tools.py  (v1.4.0)
    Excel       → tools/excel_tools.py       (v1.5.0+)

This module re-exports the original function names so older imports such as
`from tools.document_tools import create_project_report` keep working. It
deliberately defines no register_tools(), because the real modules already
register these tools — registering here too would just overwrite them.

New code should import from the specific module.
"""
from __future__ import annotations

from tools.excel_tools import (  # noqa: F401
    append_excel_row,
    create_excel,
    read_excel,
)
from tools.word_tools import (  # noqa: F401
    append_to_word_doc,
    create_project_report,
    create_word_doc,
    read_word_doc,
)

__all__ = [
    "append_excel_row",
    "append_to_word_doc",
    "create_excel",
    "create_project_report",
    "create_word_doc",
    "read_excel",
    "read_word_doc",
]
