"""Shell command guard.

FRIDAY can run arbitrary shell and PowerShell commands. That is the point of
her — but an LLM that mis-reads a request should not be one token away from
`rm -rf /` or `Format-Volume`. This module classifies a command before it runs
and lets config decide the policy:

    FRIDAY_SHELL_POLICY=confirm   (default) ask the Boss before dangerous ones
    FRIDAY_SHELL_POLICY=block               refuse dangerous ones outright
    FRIDAY_SHELL_POLICY=allow               no guard at all (old behaviour)

Only *catastrophic* patterns are flagged. Everyday work — git, pip, ls, python,
building, reading files — is never interrupted.
"""
from __future__ import annotations

import re
import sys

import config


class CommandBlocked(RuntimeError):
    """Raised when policy refuses to run a command. The agent sees the reason."""


# (compiled pattern, human explanation). Ordered most-destructive first.
DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+(/|~|\$HOME|\*)(\s|$)", re.I),
     "recursive delete of a root, home, or wildcard path"),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", re.I),
     "recursive force delete"),
    (re.compile(r"\b(mkfs|fdisk|diskpart)\b", re.I), "disk partitioning or formatting"),
    (re.compile(r"\bformat-volume\b|\bformat\s+[a-z]:", re.I), "volume format"),
    (re.compile(r"\bdd\b[^|]*\bof=/dev/", re.I), "raw write to a block device"),
    (re.compile(r">\s*/dev/(sd|nvme|hd)", re.I), "raw write to a block device"),
    (re.compile(r"\bremove-item\b.*-recurse.*-force", re.I), "recursive force delete"),
    (re.compile(r"\bdel\s+/[sq]\b|\brd\s+/s\b|\brmdir\s+/s\b", re.I),
     "recursive delete"),
    (re.compile(r":\(\)\s*\{.*\}\s*;?\s*:", re.S), "fork bomb"),
    (re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\bStop-Computer\b|\bRestart-Computer\b", re.I),
     "shutting down or rebooting the machine"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/(\s|$)", re.I), "world-writable root filesystem"),
    (re.compile(r"\b(curl|wget|iwr|Invoke-WebRequest)\b[^|;]*\|\s*(sudo\s+)?(ba)?sh", re.I),
     "piping a downloaded script straight into a shell"),
    (re.compile(r"\bgit\s+push\b.*--force", re.I), "force push"),
    (re.compile(r"\b(userdel|net\s+user\s+\S+\s+/delete)\b", re.I), "deleting a user account"),
    (re.compile(r"\breg\s+delete\b|\bRemove-ItemProperty\b.*HKLM", re.I),
     "deleting Windows registry keys"),
]


def classify(command: str) -> str | None:
    """Return a human reason if `command` looks catastrophic, else None."""
    if not command or not command.strip():
        return None
    for pattern, reason in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return reason
    return None


def _policy() -> str:
    policy = str(getattr(config, "SHELL_POLICY", "confirm")).strip().lower()
    return policy if policy in ("confirm", "block", "allow") else "confirm"


def _ask(command: str, reason: str) -> bool:
    """Prompt the Boss on the real terminal. Non-interactive → refuse."""
    if not sys.stdin or not sys.stdin.isatty():
        return False
    print(f"\n⚠  FRIDAY wants to run a potentially destructive command ({reason}):\n    {command}")
    try:
        answer = input("   Allow it? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def guard(command: str) -> None:
    """Apply the configured policy. Raises CommandBlocked to refuse.

    Returning normally means the caller may run the command.
    """
    reason = classify(command)
    if reason is None:
        return
    policy = _policy()
    config.logger.warning("dangerous command detected (%s): %s", reason, command[:200])

    if policy == "allow":
        return
    if policy == "block":
        raise CommandBlocked(
            f"Refused: this command looks destructive ({reason}). "
            "FRIDAY_SHELL_POLICY=block is set in .env. "
            "Explain the risk to the Boss and suggest a safer command."
        )
    if _ask(command, reason):
        config.logger.info("Boss approved dangerous command: %s", command[:200])
        return
    raise CommandBlocked(
        f"The Boss did not approve this command ({reason}). "
        "Do not retry it — propose a safer alternative instead."
    )
