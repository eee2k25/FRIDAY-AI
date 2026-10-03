"""GitHub cloud tools backed by GITHUB_TOKEN/GH_TOKEN or the gh CLI login."""
from __future__ import annotations

import json
from urllib.parse import quote

import requests

from core.integrations import github_token

_API = "https://api.github.com"


def _request(method: str, path: str, **kwargs):
    token = github_token()
    if not token:
        raise RuntimeError(
            "GitHub is not connected. Set GITHUB_TOKEN (or GH_TOKEN), or run 'gh auth login'."
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FRIDAY-AI",
    }
    response = requests.request(method, f"{_API}{path}", headers=headers, timeout=30, **kwargs)
    if response.status_code >= 400:
        detail = response.text[:600]
        try:
            detail = response.json().get("message", detail)
        except ValueError:
            pass
        raise RuntimeError(f"GitHub API failed ({response.status_code}): {detail}")
    return response.json() if response.content else {}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def github_list_repositories(visibility: str = "all", max_results: int = 30) -> str:
    """List repositories accessible to the connected GitHub account."""
    repos = _request("GET", "/user/repos", params={
        "visibility": visibility,
        "sort": "updated",
        "per_page": max(1, min(int(max_results), 100)),
    })
    return _json([{
        "full_name": r.get("full_name"), "private": r.get("private"),
        "description": r.get("description"), "default_branch": r.get("default_branch"),
        "updated_at": r.get("updated_at"), "url": r.get("html_url"),
    } for r in repos])


def github_list_issues(repository: str, state: str = "open", max_results: int = 30) -> str:
    """List issues (excluding pull requests) in an owner/repository GitHub project."""
    issues = _request("GET", f"/repos/{repository}/issues", params={
        "state": state, "per_page": max(1, min(int(max_results), 100)),
    })
    return _json([{
        "number": i.get("number"), "title": i.get("title"), "state": i.get("state"),
        "author": i.get("user", {}).get("login"), "labels": [x.get("name") for x in i.get("labels", [])],
        "url": i.get("html_url"),
    } for i in issues if "pull_request" not in i])


def github_create_issue(repository: str, title: str, body: str = "", labels: str = "") -> str:
    """Create a GitHub issue; labels is an optional comma-separated list."""
    payload = {"title": title, "body": body}
    if labels.strip():
        payload["labels"] = [label.strip() for label in labels.split(",") if label.strip()]
    issue = _request("POST", f"/repos/{repository}/issues", json=payload)
    return _json({"number": issue.get("number"), "title": issue.get("title"), "url": issue.get("html_url")})


def github_list_pull_requests(repository: str, state: str = "open", max_results: int = 30) -> str:
    """List pull requests in an owner/repository GitHub project."""
    pulls = _request("GET", f"/repos/{repository}/pulls", params={
        "state": state, "per_page": max(1, min(int(max_results), 100)),
    })
    return _json([{
        "number": p.get("number"), "title": p.get("title"), "state": p.get("state"),
        "draft": p.get("draft"), "author": p.get("user", {}).get("login"),
        "head": p.get("head", {}).get("label"), "base": p.get("base", {}).get("label"),
        "url": p.get("html_url"),
    } for p in pulls])


def github_get_file(repository: str, path: str, ref: str = "") -> str:
    """Read a UTF-8 text file from a GitHub repository and optional branch/tag/commit ref."""
    params = {"ref": ref} if ref else None
    item = _request("GET", f"/repos/{repository}/contents/{quote(path, safe='/')}", params=params)
    if item.get("type") != "file":
        return _json(item)
    import base64

    content = base64.b64decode(item.get("content", "")).decode("utf-8", errors="replace")
    return _json({"repository": repository, "path": item.get("path"), "sha": item.get("sha"), "content": content})


_TOOLS = (
    (github_list_repositories, {"visibility": "string", "max_results": "integer"}, []),
    (github_list_issues, {"repository": "string", "state": "string", "max_results": "integer"}, ["repository"]),
    (github_create_issue, {"repository": "string", "title": "string", "body": "string", "labels": "string"}, ["repository", "title"]),
    (github_list_pull_requests, {"repository": "string", "state": "string", "max_results": "integer"}, ["repository"]),
    (github_get_file, {"repository": "string", "path": "string", "ref": "string"}, ["repository", "path"]),
)


def register_tools(registry) -> None:
    for function, property_types, required in _TOOLS:
        registry.register_tool(function.__name__, function, {
            "name": function.__name__, "description": function.__doc__,
            "parameters": {
                "type": "object",
                "properties": {name: {"type": kind} for name, kind in property_types.items()},
                "required": required,
            },
        })
