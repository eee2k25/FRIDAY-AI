"""Credential and service helpers for FRIDAY's optional cloud extensions.

Imports for optional SDKs are deliberately lazy: FRIDAY can still start and use
all local tools when Google Workspace has not been configured.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import config

GOOGLE_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
)

CONNECTIONS_DIR = config.BASE_DIR / "memory" / "connections"
GOOGLE_TOKEN_PATH = CONNECTIONS_DIR / "google_token.json"

_GOOGLE_SERVICES = {
    "gmail": ("gmail", "v1"),
    "drive": ("drive", "v3"),
    "calendar": ("calendar", "v3"),
    "docs": ("docs", "v1"),
}


def _google_imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Workspace support is not installed. Run: pip install -e ."
        ) from exc
    return Request, Credentials, InstalledAppFlow, build


def google_client_secret_path() -> Path | None:
    configured = os.getenv("GOOGLE_CLIENT_SECRET_FILE", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend(
        [config.BASE_DIR / "client_secret.json", CONNECTIONS_DIR / "client_secret.json"]
    )
    return next((p for p in candidates if p.is_file()), None)


def _save_google_credentials(credentials: Any) -> None:
    CONNECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    GOOGLE_TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    try:
        GOOGLE_TOKEN_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # chmod is best effort on Windows


def load_google_credentials(require_valid: bool = True):
    """Load and refresh Google credentials, never starting OAuth implicitly."""
    if not GOOGLE_TOKEN_PATH.is_file():
        if require_valid:
            raise RuntimeError("Google Workspace is not connected. Run connect_google_workspace first.")
        return None
    Request, Credentials, _, _ = _google_imports()
    try:
        credentials = Credentials.from_authorized_user_file(
            str(GOOGLE_TOKEN_PATH), scopes=list(GOOGLE_SCOPES)
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "The saved Google connection is invalid. Disconnect it and connect again."
        ) from exc
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            _save_google_credentials(credentials)
        except Exception as exc:  # noqa: BLE001 - SDK exposes several auth exceptions
            raise RuntimeError(f"Google authorization refresh failed: {exc}") from exc
    if require_valid and not credentials.valid:
        raise RuntimeError("Google authorization expired. Run connect_google_workspace again.")
    return credentials


def connect_google() -> str:
    """Run Google's installed-app OAuth flow and persist the resulting refresh token."""
    secret_path = google_client_secret_path()
    if secret_path is None:
        return (
            "Google Workspace needs an OAuth desktop client first. In Google Cloud Console, "
            "enable Gmail, Drive, Calendar and Docs APIs; create an OAuth Client ID of type "
            "Desktop app; download its JSON; then set GOOGLE_CLIENT_SECRET_FILE to that path."
        )
    _, _, InstalledAppFlow, _ = _google_imports()
    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), list(GOOGLE_SCOPES))
    try:
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            authorization_prompt_message="Open this URL to connect Google Workspace:\n{url}",
            success_message="Google Workspace is connected to FRIDAY. You may close this tab.",
        )
    except Exception as exc:  # noqa: BLE001 - provide useful OAuth errors to the agent
        return f"Google Workspace connection failed: {type(exc).__name__}: {exc}"
    _save_google_credentials(credentials)
    email = getattr(credentials, "id_token", None) or {}
    identity = email.get("email", "your Google account") if isinstance(email, dict) else "your Google account"
    return f"Google Workspace connected for {identity}. Gmail, Drive, Calendar and Docs are ready."


def disconnect_google() -> str:
    """Remove FRIDAY's local Google token (the grant can also be revoked in Google Account settings)."""
    if GOOGLE_TOKEN_PATH.exists():
        GOOGLE_TOKEN_PATH.unlink()
        return "Google Workspace disconnected and its local token was removed."
    return "Google Workspace was not connected."


def google_service(name: str):
    if name not in _GOOGLE_SERVICES:
        raise ValueError(f"Unsupported Google service: {name}")
    _, _, _, build = _google_imports()
    api_name, version = _GOOGLE_SERVICES[name]
    return build(api_name, version, credentials=load_google_credentials(), cache_discovery=False)


def github_token() -> str | None:
    """Get GitHub auth from the environment or an existing gh CLI login."""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token.strip()
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def connection_status_data() -> dict[str, dict[str, Any]]:
    google = {"connected": False, "account": None, "detail": "not authorized"}
    try:
        credentials = load_google_credentials(require_valid=False)
        if credentials is not None:
            identity = getattr(credentials, "id_token", None) or {}
            google = {
                "connected": bool(credentials.valid or credentials.refresh_token),
                "account": identity.get("email") if isinstance(identity, dict) else None,
                "detail": "authorized" if credentials.valid else "refresh available",
            }
    except (RuntimeError, OSError) as exc:
        google["detail"] = str(exc)

    github_connected = github_token() is not None
    return {
        "google_workspace": {
            **google,
            "services": ["gmail", "drive", "calendar", "docs"],
        },
        "github": {
            "connected": github_connected,
            "detail": "authorized" if github_connected else "set GITHUB_TOKEN or run gh auth login",
            "services": ["repositories", "issues", "pull_requests"],
        },
        "local_git": {
            "connected": shutil.which("git") is not None,
            "detail": "git executable available" if shutil.which("git") else "git is not installed",
            "services": ["status", "commit"],
        },
    }
