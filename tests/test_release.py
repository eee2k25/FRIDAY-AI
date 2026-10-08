"""Release-level invariants.

These fail when a version bump or the Linux installer drifts, which is how
v1.5/v1.7 ended up disagreeing across four files in the first place.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXPECTED = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_module_is_the_source_of_truth():
    from version import VERSION

    assert EXPECTED.match(VERSION), f"version {VERSION!r} is not major.minor.patch"


def test_config_reports_the_release_version():
    import config
    from version import VERSION

    # config.FRIDAY_VERSION defaults to version.VERSION unless .env overrides it.
    assert config.FRIDAY_VERSION == VERSION or config.FRIDAY_VERSION


def _pyproject_version() -> str:
    """Read `version` from the [project] table without tomllib.

    tomllib only exists on Python 3.11+, and this project supports 3.10 — using
    it here made the py3.10 CI leg fail on import.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[project]", 1)
    assert len(section) == 2, "pyproject.toml has no [project] table"
    body = section[1].split("\n[", 1)[0]
    found = re.search(r'^\s*version\s*=\s*"([^"]+)"', body, flags=re.MULTILINE)
    assert found, "no version key in the [project] table"
    return found.group(1)


def test_pyproject_matches_the_version_module():
    from version import VERSION

    assert _pyproject_version() == VERSION


def test_env_example_matches_the_version_module():
    from version import VERSION

    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    found = re.search(r"^FRIDAY_VERSION=(\S+)$", text, flags=re.MULTILINE)
    assert found, ".env.example no longer pins FRIDAY_VERSION"
    assert found.group(1) == VERSION


def test_readme_heading_matches_the_version_module():
    from version import VERSION

    heading = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    major_minor = ".".join(VERSION.split(".")[:2])
    assert heading.endswith(f"v{major_minor}"), f"README heading is {heading!r}, expected v{major_minor}"


def test_version_module_is_shipped_in_the_package():
    """Otherwise `from version import VERSION` breaks in an installed wheel."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"version"' in text.split("py-modules")[1].split("]")[0]


# ------------------------------------------------------------- setup.sh ---
SETUP_SH = ROOT / "setup.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_parses():
    result = subprocess.run(
        ["bash", "-n", str(SETUP_SH)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_is_executable():
    import os

    assert os.access(SETUP_SH, os.X_OK), "setup.sh must keep its executable bit"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_supports_the_documented_flags():
    text = SETUP_SH.read_text(encoding="utf-8")
    for flag in ("--with-ollama", "--ollama-only", "--uninstall", "--help"):
        assert flag in text, f"setup.sh lost {flag}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_help_does_not_install_anything():
    """--help must exit 0 without touching the venv or ~/.local/bin."""
    result = subprocess.run(
        ["bash", str(SETUP_SH), "--help"], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, result.stderr
    assert "setup.sh" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_rejects_unknown_flags():
    result = subprocess.run(
        ["bash", str(SETUP_SH), "--definitely-not-a-flag"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode != 0
    assert "unknown option" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_uninstall_is_idempotent(tmp_path):
    """Removing a launcher that was never created must still succeed."""
    env_bin = tmp_path / "bin"
    result = subprocess.run(
        ["bash", str(SETUP_SH), "--uninstall"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "FRIDAY_BIN_DIR": str(env_bin)},
    )
    assert result.returncode == 0, result.stderr
    assert "nothing to remove" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_uninstall_removes_an_existing_launcher(tmp_path):
    env_bin = tmp_path / "bin"
    env_bin.mkdir()
    shim = env_bin / "friday"
    shim.write_text("#!/bin/sh\nexit 0\n")
    shim.chmod(0o755)

    result = subprocess.run(
        ["bash", str(SETUP_SH), "--uninstall"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "FRIDAY_BIN_DIR": str(env_bin)},
    )
    assert result.returncode == 0, result.stderr
    assert not shim.exists(), "uninstall left the launcher behind"


# ------------------------------------------------------------------ CLI ---
def test_cli_version_flag():
    result = subprocess.run(
        [sys.executable, "friday.py", "--version"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    from version import VERSION

    assert result.returncode == 0, result.stderr
    assert VERSION in result.stdout


def test_cli_doctor_flags_a_missing_provider():
    """With every key blank and Ollama off, doctor must fail loudly."""
    import os

    env = dict(os.environ)
    env.update(
        {
            "GEMINI_API_KEY": "",
            "GROQ_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "TOGETHER_API_KEY": "",
            "OPENAI_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "OLLAMA_ENABLED": "False",
            "FRIDAY_MODEL": "",
            "FRIDAY_FALLBACK_MODELS": "",
        }
    )
    result = subprocess.run(
        [sys.executable, "friday.py", "--doctor"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 1, result.stdout
    assert "no usable model provider" in result.stdout
