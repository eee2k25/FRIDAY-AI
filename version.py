"""Single source of truth for the FRIDAY release version.

Every other version string in the project reads from here so a release is a
one-line change instead of a grep-and-pray across four files. `config.py`
imports it, and `tests/test_release.py` asserts the copies agree.
"""
from __future__ import annotations

VERSION = "1.8.0"

__all__ = ["VERSION"]
