"""Connection management for FRIDAY's optional cloud extensions."""
from __future__ import annotations

import json

from core.integrations import connect_google, connection_status_data, disconnect_google


def list_connections() -> str:
    """Show connection state and available services for Google Workspace, GitHub and local Git."""
    return json.dumps(connection_status_data(), indent=2)


def connect_google_workspace() -> str:
    """Connect Gmail, Drive, Calendar and Google Docs with one browser-based OAuth grant."""
    return connect_google()


def disconnect_google_workspace() -> str:
    """Remove FRIDAY's saved Google Workspace authorization from this computer."""
    return disconnect_google()


def register_tools(registry) -> None:
    declarations = (
        ("list_connections", list_connections, {}, []),
        ("connect_google_workspace", connect_google_workspace, {}, []),
        ("disconnect_google_workspace", disconnect_google_workspace, {}, []),
    )
    for name, function, properties, required in declarations:
        registry.register_tool(
            name,
            function,
            {
                "name": name,
                "description": function.__doc__,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        )
