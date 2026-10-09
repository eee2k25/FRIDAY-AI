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


# ------------------------------------------------- Codespace model server ---
OLLAMA_SH = ROOT / "deploy" / "codespaces" / "ollama-server.sh"
DEVCONTAINER_JSON = ROOT / ".devcontainer" / "devcontainer.json"
OLLAMA_HOOK = ROOT / ".devcontainer" / "start-ollama.sh"


def _bash_ok(script: Path) -> None:
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_ollama_server_script_parses():
    _bash_ok(OLLAMA_SH)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_ollama_start_hook_parses():
    _bash_ok(OLLAMA_HOOK)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_ollama_server_script_is_executable():
    import os

    assert os.access(OLLAMA_SH, os.X_OK), "ollama-server.sh must keep its executable bit"


def test_ollama_server_script_supports_the_documented_subcommands():
    """Every advertised subcommand must be a real label in the case block."""
    lines = OLLAMA_SH.read_text(encoding="utf-8").splitlines()
    labels: set[str] = set()
    inside = False
    for line in lines:
        if line.startswith("case \"$cmd\" in"):
            inside = True
            continue
        if inside:
            if line.strip().startswith("esac"):
                break
            # Labels and bodies share a line: `start|up)  do_start ;;`
            head = line.strip().split(")", 1)[0]
            labels.update(part.strip() for part in head.split("|"))
    for sub in (
        "install", "start", "stop", "restart", "status", "logs", "pull", "test",
        "url", "watch", "autostart", "wire", "help",
    ):
        assert sub in labels, f"ollama-server.sh lost '{sub}'"


def test_ollama_server_script_binds_for_port_forwarding():
    """A Codespace proxy can only reach a listener on 0.0.0.0."""
    text = OLLAMA_SH.read_text(encoding="utf-8")
    assert "0.0.0.0" in text
    assert "OLLAMA_HOST" in text and "OLLAMA_MODELS" in text


def test_devcontainer_starts_the_server_on_every_resume():
    """postCreateCommand runs once; only postStartCommand survives a stop/start.

    Without this the model server is dead on every second day of use, which is
    the single most common "FRIDAY stopped working" report for Codespaces.
    """
    text = DEVCONTAINER_JSON.read_text(encoding="utf-8")
    assert "postStartCommand" in text, "no boot hook — ollama serve will not come back"
    assert "start-ollama.sh" in text
    assert "11434" in text, "Ollama's port is not forwarded/labelled"


def test_setup_sh_delegates_ollama_to_one_implementation():
    """Two copies of the install logic is how a Codespace ends up half-set-up."""
    text = (ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "ollama-server.sh" in text, "setup.sh no longer uses deploy/codespaces/ollama-server.sh"


def test_env_example_declares_each_key_once():
    """A duplicated key silently picks one value and hides the other.

    .env.example carried three OLLAMA_BASE_URL lines at once — one of them a dead
    Codespace URL — which made `cp .env.example .env` a coin flip.
    """
    import re as _re

    keys = [
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if _re.match(r"^[A-Z][A-Z0-9_]*=", line)
    ]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"duplicated active keys in .env.example: {sorted(dupes)}"


def test_no_shipped_file_hardcodes_a_codespace_url():
    """Forwarded URLs are per-Codespace; pasting one into git rots immediately."""
    import re as _re

    pattern = _re.compile(r"https://[a-z0-9][a-z0-9-]*-[0-9]+\.(?:preview\.)?app\.github\.dev")
    checked = ["config.py", ".env.example", "README.md", "CODESPACES_GUIDE.md", "setup.sh",
               ".devcontainer/devcontainer.json", "deploy/codespaces/ollama-server.sh"]
    offenders = {}
    for rel in checked:
        path = ROOT / rel
        if not path.exists():
            continue
        found = pattern.findall(path.read_text(encoding="utf-8"))
        if found:
            offenders[rel] = found
    assert not offenders, f"Codespace-specific URLs committed in: {offenders}"
