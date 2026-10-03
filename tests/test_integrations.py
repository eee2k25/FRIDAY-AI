"""Tests for optional Google Workspace and GitHub extensions."""
from __future__ import annotations

import json

from core import integrations
from core.tool_registry import ToolRegistry
from tools import extension_tools, github_tools, google_workspace_tools


def test_extension_tools_register_connection_management():
    registry = ToolRegistry()
    extension_tools.register_tools(registry)
    assert set(registry.tools) == {
        "list_connections",
        "connect_google_workspace",
        "disconnect_google_workspace",
    }


def test_google_workspace_tools_register_all_services():
    registry = ToolRegistry()
    google_workspace_tools.register_tools(registry)
    assert {
        "gmail_search",
        "gmail_send_email",
        "drive_search",
        "drive_upload_file",
        "calendar_list_events",
        "calendar_create_event",
        "docs_read",
        "docs_create",
    } <= set(registry.tools)


def test_connect_google_without_client_secret_is_actionable(monkeypatch):
    monkeypatch.setattr(integrations, "google_client_secret_path", lambda: None)
    message = integrations.connect_google()
    assert "OAuth Client ID" in message
    assert "GOOGLE_CLIENT_SECRET_FILE" in message


def test_connection_status_does_not_require_google_sdk_without_token(monkeypatch, tmp_path):
    monkeypatch.setattr(integrations, "GOOGLE_TOKEN_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(integrations, "github_token", lambda: None)
    status = integrations.connection_status_data()
    assert status["google_workspace"]["connected"] is False
    assert status["google_workspace"]["services"] == ["gmail", "drive", "calendar", "docs"]
    assert status["github"]["connected"] is False


def test_github_list_issues_filters_pull_requests(monkeypatch):
    payload = [
        {"number": 1, "title": "Bug", "state": "open", "user": {"login": "dev"}, "labels": []},
        {"number": 2, "title": "PR", "pull_request": {}, "user": {"login": "dev"}},
    ]
    monkeypatch.setattr(github_tools, "_request", lambda *args, **kwargs: payload)
    result = json.loads(github_tools.github_list_issues("owner/repo"))
    assert [item["number"] for item in result] == [1]
